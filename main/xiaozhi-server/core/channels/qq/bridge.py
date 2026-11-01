"""Authenticated event API, per-route queues and persistent duplicate suppression."""
import asyncio
import hashlib
import hmac
import json
import re
import sqlite3
import time
from pathlib import Path

from aiohttp import web

from .media import outbound_segments
from .onebot import OneBot
from .session import NativeSession, BindingRequired
from .settings import qq_id


class QQBridge:
    def __init__(self, settings, config, server, onebot=None, session_factory=None):
        self.settings, self.config, self.server = settings, config, server
        self.onebot = onebot or OneBot(settings)
        self.session_factory = session_factory or NativeSession
        self.sessions, self.queues, self.tasks = {}, {}, []
        self.errors = {}
        self.error_stages = {}
        self.db = None
        self.closing = False
        self.accepted = 0

    def register(self, app):
        app.add_routes([
            web.get("/xiaozhi/qq/status", self.status),
            web.post("/xiaozhi/qq/events", self.events),
            web.get("/xiaozhi/qq/events/{event_id}", self.receipt),
            web.post("/xiaozhi/qq/bindings/{route_id}/prepare", self.prepare),
            web.post("/xiaozhi/qq/send", self.send),
        ])
        app.on_startup.append(self.start)
        app.on_cleanup.append(self.close)

    async def start(self, app=None):
        path = Path(self.settings.state_path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, route TEXT NOT NULL, state TEXT NOT NULL, error TEXT, created REAL NOT NULL)")
        self.db.execute("UPDATE events SET state='interrupted' WHERE state IN ('queued','processing')")
        self.db.execute("DELETE FROM events WHERE created < ?", (time.time() - 7 * 86400,))
        self.db.commit()
        await self.onebot.start()
        for name, route in self.settings.routes.items():
            self.queues[name] = asyncio.Queue(maxsize=16)
            self.sessions[name] = self.session_factory(route, self.settings, self.config, self.server, self.onebot)
            self.tasks.append(asyncio.create_task(self._worker(name)))
        if self.settings.websocket_url:
            self.tasks.append(asyncio.create_task(self.onebot.listen(self.ingest, self.disconnect)))

    def authorize(self, request):
        supplied = request.headers.get("Authorization", "")
        expected = "Bearer " + self.settings.api_key
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise web.HTTPUnauthorized(text="QQ API authentication required")

    async def events(self, request):
        raw = await request.clone(client_max_size=256 * 1024).read()
        secret = self.settings.webhook_secret
        signature = request.headers.get("X-Signature", "")
        if secret and signature:
            expected = "sha1=" + hmac.new(secret.encode(), raw, hashlib.sha1).hexdigest()
            if not hmac.compare_digest(signature.encode(), expected.encode()):
                raise web.HTTPUnauthorized(text="Invalid OneBot signature")
        else:
            self.authorize(request)
        try:
            result = await self.ingest(json.loads(raw))
        except OverflowError:
            raise web.HTTPTooManyRequests(text="QQ route queue is full")
        except (ValueError, TypeError, KeyError, AttributeError):
            raise web.HTTPBadRequest(text="Invalid OneBot message event")
        return web.json_response(result, status=202 if result["state"] == "queued" else 200)

    async def ingest(self, event):
        if not isinstance(event, dict):
            raise ValueError("Expected an event object")
        if event.get("post_type") != "message" or str(event.get("self_id")) != self.settings.self_id:
            return {"state": "ignored"}
        user = qq_id(event.get("user_id", ""))
        if user == self.settings.self_id:
            return {"state": "ignored"}
        kind = event.get("message_type")
        peer = str(event.get("group_id")) if kind == "group" else user
        route = next((r for r in self.settings.routes.values() if r.kind == kind and r.peer_id == peer), None)
        if not route or (route.members and user not in route.members):
            return {"state": "ignored"}
        now = time.time()
        at = event.get("time")
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not now - self.settings.max_event_age <= at <= now + 60:
            return {"state": "ignored", "reason": "stale_event"}
        parts = event.get("message")
        if isinstance(parts, str):
            # Plain text stays plain text, including literal [CQ:...] sequences.
            parts = [{"type": "text", "data": {"text": parts}}]
        if not isinstance(parts, list) or not 1 <= len(parts) <= 32:
            raise ValueError("Invalid message segments")
        for part in parts:
            if not isinstance(part, dict) or not isinstance(part.get("type"), str) or not isinstance(part.get("data"), dict):
                raise ValueError("Invalid message segment")
            if part["type"] == "text" and (not isinstance(part["data"].get("text"), str) or len(part["data"]["text"]) > 8000):
                raise ValueError("Invalid text")
        if kind == "group" and route.require_at and not any(p["type"] == "at" and str(p["data"].get("qq")) == self.settings.self_id for p in parts):
            return {"state": "ignored", "reason": "not_mentioned"}
        message_id = str(event.get("message_id", ""))
        if not re.fullmatch(r"-?[0-9]{1,20}", message_id):
            raise ValueError("Missing message_id")
        key = hashlib.sha256(f"{self.settings.self_id}:{route.id}:{message_id}".encode()).hexdigest()[:32]
        existing = self.db.execute("SELECT state FROM events WHERE id=?", (key,)).fetchone()
        if existing:
            return {"state": "duplicate", "event_id": key, "delivery_state": existing[0]}
        if self.closing or self.queues[route.id].full():
            raise OverflowError("Queue is full")
        with self.db:
            self.db.execute("INSERT INTO events VALUES (?,?,'queued',NULL,?)", (key, route.id, now))
            self.accepted += 1
            if self.accepted % 128 == 0:
                self.db.execute("DELETE FROM events WHERE created < ?", (now - 7 * 86400,))
        self.queues[route.id].put_nowait((key, {**event, "message": parts}))
        return {"state": "queued", "event_id": key, "route_id": route.id}

    async def _worker(self, name):
        while True:
            key, event = await self.queues[name].get()
            try:
                self._update(key, "processing")
                await asyncio.wait_for(self._process(name, event), timeout=self.settings.turn_timeout)
                self._update(key, "completed")
                self.errors.pop(name, None)
                self.error_stages.pop(name, None)
            except asyncio.CancelledError:
                self._update(key, "interrupted")
                raise
            except Exception as exc:
                error = "binding_required" if isinstance(exc, BindingRequired) else type(exc).__name__
                self.errors[name] = error
                self.error_stages[name] = self.sessions[name].stage
                self._update(key, "failed", error)
                await self.sessions[name].close()
            finally:
                self.queues[name].task_done()

    async def _process(self, name, event):
        self.sessions[name].stage = "connecting_onebot"
        await self.onebot.verify_account()
        await self.sessions[name].turn(event)

    def _update(self, key, state, error=None):
        with self.db:
            self.db.execute("UPDATE events SET state=?,error=? WHERE id=?", (state, error, key))

    async def status(self, request):
        self.authorize(request)
        return web.json_response({"enabled": True, "protocol": "onebot-v11", "self_id": self.settings.self_id,
            "onebot_connected": self.onebot.connected, "routes": [
                {"id": name, "kind": r.kind, "peer_id": r.peer_id, "device_id": r.device_id,
                 "reply_mode": r.reply_mode, "connected": self.sessions[name].connected,
                 "queued": self.queues[name].qsize(), "last_error": self.errors.get(name),
                 "error_stage": self.error_stages.get(name)}
                for name, r in self.settings.routes.items()]})

    async def receipt(self, request):
        self.authorize(request)
        row = self.db.execute("SELECT route,state,error FROM events WHERE id=?", (request.match_info["event_id"],)).fetchone()
        if not row:
            raise web.HTTPNotFound()
        return web.json_response({"route_id": row[0], "state": row[1], "error": row[2]})

    async def prepare(self, request):
        self.authorize(request)
        session = self.sessions.get(request.match_info["route_id"])
        if not session:
            raise web.HTTPNotFound(text="Unknown route")
        try:
            return web.json_response(await session.prepare())
        except Exception:
            raise web.HTTPBadGateway(text="Cannot register QQ device with the console OTA API")

    async def send(self, request):
        self.authorize(request)
        try:
            data = await request.clone(client_max_size=8 * 1024 * 1024).json()
            route = self.settings.routes.get(data.get("route_id"))
            if not route:
                raise web.HTTPNotFound(text="Unknown route")
            segments = await outbound_segments(data.get("message"), self.settings.media_allowed_origins)
        except (ValueError, TypeError, AttributeError):
            raise web.HTTPBadRequest(text="Invalid outgoing message")
        try:
            message_id = await self.onebot.send(route, segments)
            return web.json_response({"message_id": message_id})
        except Exception:
            raise web.HTTPBadGateway(text="QQ delivery failed; check status before retrying")

    async def disconnect(self):
        await asyncio.gather(*(s.close() for s in self.sessions.values()), return_exceptions=True)

    async def close(self, app=None):
        self.closing = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.disconnect()
        await self.onebot.close()
        if self.db:
            self.db.close()
