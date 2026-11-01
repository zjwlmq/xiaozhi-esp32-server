"""OneBot actions use the operator's endpoint, never a URL supplied by an event."""
import asyncio
import json
import time

import aiohttp


class OneBotError(RuntimeError):
    pass


class OneBot:
    def __init__(self, settings):
        self.settings = settings
        self.http = None
        self.connected = False
        self.checked_at = 0

    async def start(self):
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20), trust_env=False)

    @property
    def headers(self):
        token = self.settings.access_token
        return {"Authorization": "Bearer " + token} if token else {}

    async def call(self, action, params=None):
        async with self.http.post(self.settings.http_url + "/" + action, json=params or {},
                                  headers=self.headers, allow_redirects=False) as response:
            if response.status != 200:
                raise OneBotError(f"OneBot HTTP {response.status}")
            chunks, size = [], 0
            async for chunk in response.content.iter_chunked(65536):
                size += len(chunk)
                if size > 12 * 1024 * 1024:
                    raise OneBotError("OneBot response too large")
                chunks.append(chunk)
            data = json.loads(b"".join(chunks))
            if data.get("status") != "ok" or data.get("retcode") != 0:
                # Do not expose upstream URLs, credentials or message content in errors.
                raise OneBotError("OneBot action failed")
            return data.get("data") or {}

    async def verify_account(self):
        if time.monotonic() - self.checked_at < 5:
            return
        self.connected = False
        account = await self.call("get_login_info")
        if str(account.get("user_id")) != self.settings.self_id:
            raise OneBotError("OneBot account does not match configured self_id")
        self.checked_at = time.monotonic()
        self.connected = True

    async def send(self, route, segments):
        await self.verify_account()
        field = "user_id" if route.kind == "private" else "group_id"
        # No automatic retry: a timeout may occur after QQ has accepted a message.
        result = await self.call("send_" + route.kind + "_msg",
                                 {field: int(route.peer_id), "message": segments})
        if "message_id" not in result:
            raise OneBotError("OneBot did not acknowledge message delivery")
        return str(result["message_id"])

    async def listen(self, consume, disconnected):
        while True:
            try:
                await self.verify_account()
                async with self.http.ws_connect(self.settings.websocket_url, headers=self.headers,
                                                heartbeat=25, max_msg_size=256 * 1024) as ws:
                    async for frame in ws:
                        if frame.type == aiohttp.WSMsgType.TEXT:
                            try:
                                await consume(json.loads(frame.data))
                            except (ValueError, TypeError, KeyError, OverflowError):
                                continue
                        elif frame.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                            break
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, OneBotError, asyncio.TimeoutError, ValueError):
                pass
            finally:
                self.connected = False
                self.checked_at = 0
                await disconnected()
            await asyncio.sleep(5)

    async def close(self):
        if self.http:
            await self.http.close()
