"""Local end-to-end tests. Real HTTP, bridge, chat method and text output; fake model/QQ."""
import ast
import asyncio
import base64
import hashlib
import hmac
import json
import io
import logging
import sys
import shutil
import tempfile
import threading
import time
import unittest
import uuid
import wave
from pathlib import Path
from types import SimpleNamespace, MethodType
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "main/xiaozhi-server"
sys.path.insert(0, str(SERVER))
from core.channels.qq.bridge import QQBridge
from core.channels.qq.settings import Settings
from core.channels.qq.session import NativeSession
from core.channels.qq.text_tts import TextTTS
from core.channels.qq.media import download, outbound_segments, pcm_audio
from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO
from core.utils.dialogue import Dialogue, Message
from core.utils.nixi_roleplay_guard import NixiStreamingOutputGuard, is_nixi_roleplay_prompt

KEY = "test-only-qq-api-key-" + "x" * 32
SECRET = "test-only-onebot-webhook-" + "y" * 32
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1sAAAAASUVORK5CYII=")


def config(path="unused.sqlite3", **overrides):
    return {"enabled": True, "api_key": KEY, "webhook_secret": SECRET, "self_id": "100001",
            "http_url": "http://127.0.0.1:1", "state_path": path,
            "routes": [{"id": "alice", "peer_id": "200001"}, {"id": "bob", "peer_id": "200002"},
                       {"id": "group", "kind": "group", "peer_id": "300001", "members": ["200001"]}], **overrides}


def event(number=1, peer="200001", text="你好 🙂", **changes):
    return {"time": int(time.time()), "post_type": "message", "self_id": 100001,
            "message_type": "private", "message_id": number, "user_id": int(peer),
            "message": [{"type": "text", "data": {"text": text}}], **changes}


def real_method(name, namespace):
    path = SERVER / "core/connection.py"
    cls = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(n, ast.ClassDef) and n.name == "ConnectionHandler")
    method = next(n for n in cls.body if getattr(n, "name", None) == name)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


class FakeConnection:
    """Substitute hardware/service setup; execute the production chat method unchanged."""
    def __init__(self, owner, channel_type):
        self.owner, self.channel_type = owner, channel_type
        self.components_ready = asyncio.Event()
        self.components_error = None
        self.need_bind = False
        self.config = {}
        self.stop_event = threading.Event()
        self.client_abort = False
        self.client_have_voice = False
        self.client_is_speaking = False
        self.features = {"emoji": False}
        self.sentence_id = None
        self.session_id = str(uuid.uuid4())
        self.memory = None
        self.intent_type = "nointent"
        self.current_speaker = None
        self.system_introduced_speakers = set()
        self.prompt = "测试角色"
        self.dialogue = Dialogue()
        self.logger = Mock()
        self.logger.bind.return_value = self.logger
        self.plugin_runtime = SimpleNamespace(refresh=AsyncMock(), begin_turn=Mock(),
                                               prepare_memory=lambda memory, _: memory, record_sent=Mock())
        self.asr = SimpleNamespace(speech_to_text_wrapper=AsyncMock(return_value=("语音里的话", None)))
        self.llm = SimpleNamespace(response=self.respond)
        self.tts = TextTTS()
        namespace = dict(asyncio=asyncio, json=json, uuid=uuid, TAG="test", Message=Message,
                         TTSMessageDTO=TTSMessageDTO, ContentType=ContentType, SentenceType=SentenceType,
                         NixiStreamingOutputGuard=NixiStreamingOutputGuard, is_nixi_roleplay_prompt=is_nixi_roleplay_prompt,
                         get_system_error_response=lambda _: "model_error")
        self.chat = MethodType(real_method("chat", namespace), self)

    def respond(self, session_id, messages):
        self.owner.model_calls.append((self.device_id, messages))
        return iter(["收到：", messages[-1]["content"], " 🙂"])

    async def handle_connection(self, socket):
        self.websocket = socket
        self.device_id = socket.request.headers["device-id"]
        self.loop = asyncio.get_running_loop()
        self.dialogue.put(Message(role="system", content="角色绑定到 " + self.device_id))
        await self.tts.open_audio_channels(self)
        self.components_ready.set()
        try:
            async for _ in socket:
                pass
        finally:
            self.stop_event.set()
            await self.tts.close()

    async def _route_message(self, value):
        if self.owner.gate:
            await self.owner.gate.wait()
        data = json.loads(value)
        self.client_is_speaking = True
        await asyncio.to_thread(self.chat, data["text"])

    def clearSpeakStatus(self):
        self.client_is_speaking = False


class FakeServer:
    def __init__(self):
        self.model_calls, self.connections = [], []
        self.gate = None

    def create_connection(self, channel_type=None):
        conn = FakeConnection(self, channel_type)
        self.connections.append(conn)
        return conn


class SettingsTests(unittest.TestCase):
    def test_disabled_and_missing_secret(self):
        self.assertIsNone(Settings.parse({}))
        with self.assertRaises(ValueError):
            Settings.parse(config(api_key="short"))

    def test_virtual_device_is_stable_and_distinct(self):
        first = Settings.parse(config())
        other = config()
        other["routes"][0]["id"] = "renamed"
        self.assertEqual(first.routes["alice"].device_id, Settings.parse(other).routes["renamed"].device_id)
        self.assertEqual(len({r.device_id for r in first.routes.values()}), 3)

    def test_no_duplicate_route_or_url_credentials(self):
        with self.assertRaises(ValueError):
            Settings.parse(config(routes=[{"id": "a", "peer_id": "200001"}, {"id": "b", "peer_id": "200001"}]))
        with self.assertRaises(ValueError):
            Settings.parse(config(http_url="http://secret:token@localhost:3000"))

    def test_text_only_does_not_initialize_speech_provider(self):
        factory = Mock(side_effect=AssertionError("Speech provider must not be called"))
        method = real_method("_initialize_tts", {"initialize_tts": factory})
        result = method(SimpleNamespace(channel_type="qq_text"))
        self.assertIsInstance(result, TextTTS)
        factory.assert_not_called()


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.getLogger("asyncio").setLevel(logging.ERROR)
        self.tmp = tempfile.TemporaryDirectory()
        self.sent, self.actions = [], []
        self.fail_sends = False
        self.login_id = 100001
        self.fake_server = FakeServer()
        app = web.Application()
        app.router.add_post("/{action}", self.onebot_action)
        async def picture(_):
            return web.Response(body=PNG, content_type="image/png")
        app.router.add_get("/media.png", picture)
        async def websocket_events(request):
            self.assertEqual(request.headers.get("Authorization"), "Bearer local-test-token")
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json(event(number=800, text="来自正向WS"))
            async for _ in ws:
                pass
            return ws
        async def ota(request):
            self.assertEqual(request.headers["Device-Id"], self.settings.routes["alice"].device_id)
            self.assertEqual((await request.json())["application"]["name"], "xiaozhi-qq")
            return web.json_response({"activation": {"code": "123456"}, "websocket": {"token": "must-not-expose"}})
        app.router.add_get("/events", websocket_events)
        app.router.add_post("/xiaozhi/ota/", ota)
        self.onebot_server = TestServer(app)
        await self.onebot_server.start_server()
        self.settings = Settings.parse(config(str(Path(self.tmp.name) / "events.sqlite3"),
            http_url=str(self.onebot_server.make_url("")), access_token="local-test-token",
            media_allowed_origins=[str(self.onebot_server.make_url("")).rstrip("/")]))
        await self.start_bridge()

    async def start_bridge(self):
        self.bridge = QQBridge(self.settings, {}, self.fake_server)
        app = web.Application()
        self.bridge.register(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        if self.fake_server.gate:
            self.fake_server.gate.set()
        await self.client.close()
        await self.onebot_server.close()
        self.tmp.cleanup()

    async def onebot_action(self, request):
        self.assertEqual(request.headers.get("Authorization"), "Bearer local-test-token")
        action = request.match_info["action"]
        params = await request.json()
        self.actions.append((action, params))
        if action == "get_login_info":
            data = {"user_id": self.login_id}
        elif action == "get_record":
            data = {"base64": base64.b64encode(b"fake WAV input").decode()}
        else:
            if self.fail_sends:
                return web.json_response({"status": "failed", "retcode": 100, "wording": "secret-do-not-leak"})
            self.sent.append((action, params))
            data = {"message_id": len(self.sent)}
        return web.json_response({"status": "ok", "retcode": 0, "data": data})

    async def post(self, payload, headers=None):
        return await self.client.post("/xiaozhi/qq/events", json=payload,
                                      headers=headers if headers is not None else {"Authorization": "Bearer " + KEY})

    async def drain(self):
        await asyncio.wait_for(asyncio.gather(*(q.join() for q in self.bridge.queues.values())), 5)

    async def test_event_reaches_real_chat_and_onebot_once(self):
        payload = event()
        response = await self.post(payload)
        self.assertEqual(response.status, 202)
        accepted = await response.json()
        await self.drain()
        self.assertEqual(self.sent[0][1]["message"], [{"type": "text", "data": {"text": "收到：你好 🙂 🙂"}}])
        self.assertEqual((await (await self.post(payload)).json())["state"], "duplicate")
        self.assertEqual(len(self.sent), 1)
        receipt = await self.client.get("/xiaozhi/qq/events/" + accepted["event_id"], headers={"Authorization": "Bearer " + KEY})
        self.assertEqual((await receipt.json())["state"], "completed")
        runtime = self.fake_server.connections[0].plugin_runtime
        self.assertEqual(runtime.begin_turn.call_args.kwargs["event_at"].timestamp(), payload["time"])
        runtime.record_sent.assert_called_once()

    async def test_auth_signature_tampering_and_body_limit(self):
        self.assertEqual((await self.post(event(), {})).status, 401)
        body = json.dumps(event()).encode()
        signature = "sha1=" + hmac.new(SECRET.encode(), body, hashlib.sha1).hexdigest()
        response = await self.client.post("/xiaozhi/qq/events", data=body, headers={"X-Signature": signature})
        self.assertEqual(response.status, 202)
        bad = await self.client.post("/xiaozhi/qq/events", data=body + b" ", headers={"X-Signature": signature})
        self.assertEqual(bad.status, 401)
        huge = await self.client.post("/xiaozhi/qq/events", data=b"x" * (256 * 1024 + 1))
        self.assertEqual(huge.status, 413)
        await self.drain()

    async def test_unlisted_self_wrong_bot_and_stale_are_ignored(self):
        for payload in [event(peer="900001"), event(peer="100001"), event(self_id=100002),
                        event(time=time.time() - 601), event(time=time.time() + 61)]:
            self.assertEqual((await (await self.post(payload)).json())["state"], "ignored")
        self.assertFalse(self.sent)
        self.assertFalse(self.fake_server.model_calls)

    async def test_group_requires_mention_and_member_allowlist(self):
        base = event(message_type="group", group_id=300001)
        self.assertEqual((await (await self.post(base)).json())["reason"], "not_mentioned")
        base["message"].insert(0, {"type": "at", "data": {"qq": "100001"}})
        self.assertEqual((await self.post(base)).status, 202)
        await self.drain()
        self.assertEqual(self.sent[0][0], "send_group_msg")
        self.assertEqual(self.sent[0][1]["group_id"], 300001)
        base["user_id"] = 200002
        base["message_id"] = 2
        self.assertEqual((await (await self.post(base)).json())["state"], "ignored")

    async def test_conversations_are_separate_and_each_retains_history(self):
        await asyncio.gather(self.post(event(text="A的秘密")), self.post(event(peer="200002", text="B的话")))
        await self.drain()
        await self.post(event(number=2, text="A的第二句"))
        await self.drain()
        aid = self.settings.routes["alice"].device_id
        bid = self.settings.routes["bob"].device_id
        alice = [history for device, history in self.fake_server.model_calls if device == aid][-1]
        bob = [history for device, history in self.fake_server.model_calls if device == bid][-1]
        self.assertIn("A的秘密", json.dumps(alice, ensure_ascii=False))
        self.assertNotIn("B的话", json.dumps(alice, ensure_ascii=False))
        self.assertNotIn("A的秘密", json.dumps(bob, ensure_ascii=False))

    async def test_persistent_dedup_after_restart(self):
        await self.post(event())
        await self.drain()
        await self.client.close()
        await self.start_bridge()
        self.assertEqual((await (await self.post(event())).json())["state"], "duplicate")
        self.assertEqual(len(self.sent), 1)

    async def test_failed_delivery_is_reported_and_not_retried(self):
        self.fail_sends = True
        response = await (await self.post(event())).json()
        await self.drain()
        status = self.bridge.db.execute("SELECT state,error FROM events WHERE id=?", (response["event_id"],)).fetchone()
        self.assertEqual(status[0], "failed")
        self.assertEqual(len([a for a, _ in self.actions if a.startswith("send_")]), 1)
        self.assertNotIn("secret", str(self.bridge.errors))

    async def test_wrong_bot_never_calls_model_or_sends(self):
        self.login_id = 100009
        await self.post(event())
        await self.drain()
        self.assertFalse(self.sent)
        self.assertFalse(self.fake_server.model_calls)

    async def test_image_and_face_are_given_to_bound_agent(self):
        parts = [{"type": "image", "data": {"url": str(self.onebot_server.make_url("/media.png"))}},
                 {"type": "face", "data": {"id": "14"}}]
        with patch.object(NativeSession, "describe_image", AsyncMock(return_value="一只猫")) as vision:
            await self.post(event(message=parts))
            await self.drain()
            vision.assert_awaited_once()
        text = self.fake_server.model_calls[-1][1][-1]["content"]
        self.assertIn("一只猫", text)
        self.assertIn("QQ表情 id=14", text)

    async def test_record_uses_onebot_decode_then_configured_asr(self):
        with patch("core.channels.qq.session.pcm_audio", AsyncMock(return_value=[b"\0" * 1920])) as convert:
            await self.post(event(message=[{"type": "record", "data": {"file": "example.silk"}}]))
            await self.drain()
            convert.assert_awaited_once_with(b"fake WAV input")
        self.assertIn("语音里的话", self.fake_server.model_calls[-1][1][-1]["content"])

    async def test_send_supports_sticker_face_and_literal_cq_text(self):
        payload = {"route_id": "alice", "message": [
            {"type": "image", "data": {"file": "base64://" + base64.b64encode(PNG).decode()}},
            {"type": "face", "data": {"id": "14"}},
            {"type": "text", "data": {"text": "[CQ:at,qq=all]"}}]}
        response = await self.client.post("/xiaozhi/qq/send", json=payload, headers={"Authorization": "Bearer " + KEY})
        self.assertEqual(response.status, 200)
        self.assertEqual([x["type"] for x in self.sent[0][1]["message"]], ["image", "face", "text"])
        self.assertEqual(self.sent[0][1]["message"][-1]["data"]["text"], "[CQ:at,qq=all]")
        payload["route_id"] = "unlisted"
        self.assertEqual((await self.client.post("/xiaozhi/qq/send", json=payload, headers={"Authorization": "Bearer " + KEY})).status, 404)

    async def test_generated_image_is_forwarded_to_correct_peer(self):
        await self.post(event())
        await self.drain()
        session = self.bridge.sessions["alice"]
        await session._outgoing(json.dumps({"type": "plugin_image", "url": "data:image/png;base64," + base64.b64encode(PNG).decode()}))
        self.assertEqual(self.sent[-1][1]["user_id"], 200001)
        self.assertEqual(self.sent[-1][1]["message"][0]["type"], "image")

    async def test_no_local_file_or_private_media_without_operator_allowlist(self):
        for source in ["file:///etc/passwd", "C:\\secret.png", "http://127.0.0.1:1234/a", "https://127.0.0.1/a"]:
            with self.assertRaises(ValueError):
                await download(source)
        with self.assertRaises(ValueError):
            await outbound_segments([{"type": "at", "data": {"qq": "all"}}])

    async def test_forward_websocket_events_and_graceful_shutdown(self):
        await self.client.close()
        self.settings.websocket_url = str(self.onebot_server.make_url("/events")).replace("http:", "ws:")
        await self.start_bridge()
        for _ in range(100):
            if self.sent:
                break
            await asyncio.sleep(0.02)
        self.assertEqual(self.sent[0][1]["message"][0]["data"]["text"], "收到：来自正向WS 🙂")
        await self.drain()
        await self.client.close()
        self.assertTrue(all(task.done() for task in self.bridge.tasks))

    async def test_queue_backpressure_does_not_accept_or_lose_excess_event(self):
        self.fake_server.gate = asyncio.Event()
        await self.post(event())
        for _ in range(100):
            if self.fake_server.connections:
                break
            await asyncio.sleep(0.01)
        for i in range(2, 18):
            self.assertEqual((await self.post(event(number=i))).status, 202)
        self.assertEqual((await self.post(event(number=18))).status, 429)
        self.assertEqual(self.bridge.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 17)
        self.fake_server.gate.set()
        await self.drain()
        self.assertEqual(len(self.sent), 17)

    async def test_prepare_returns_binding_code_only_to_authenticated_operator(self):
        session = self.bridge.sessions["alice"]
        session.config = {"read_config_from_api": True, "manager-api": {"url": str(self.onebot_server.make_url("/xiaozhi"))}}
        path = "/xiaozhi/qq/bindings/alice/prepare"
        self.assertEqual((await self.client.post(path)).status, 401)
        response = await self.client.post(path, headers={"Authorization": "Bearer " + KEY})
        result = await response.json()
        self.assertEqual(result["activation_code"], "123456")
        self.assertNotIn("must-not-expose", json.dumps(result))
        self.assertFalse(self.sent)

    async def test_media_dns_pinning_and_redirect_block(self):
        with patch("core.channels.qq.media.resolve_endpoint", AsyncMock(side_effect=ValueError("private DNS"))):
            with self.assertRaises(ValueError):
                await download("https://untrusted.example/image.png")
        class Response:
            status_code = 302
        class Stream:
            async def __aenter__(self): return Response()
            async def __aexit__(self, *args): pass
        class Client:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def stream(self, *args, **kwargs): return Stream()
        with patch("core.channels.qq.media.httpx.AsyncClient", return_value=Client()):
            with self.assertRaises(ValueError):
                await download(str(self.onebot_server.make_url("/redirect")), self.settings.media_allowed_origins)

    async def test_voice_reply_waits_for_onebot_ack_before_recording(self):
        await self.post(event())
        await self.drain()
        session = self.bridge.sessions["alice"]
        from dataclasses import replace
        session.route = replace(session.route, reply_mode="voice")
        session.done.clear()
        session.conn.plugin_runtime.record_sent.reset_mock()
        await session._outgoing(b"fake-opus-frame")
        session.conn.plugin_runtime.record_sent.assert_not_called()
        codec = Mock(return_value=b"RIFF-fake-wav")
        with patch.dict(sys.modules, {"core.utils.util": SimpleNamespace(opus_datas_to_wav_bytes=codec)}):
            await session._outgoing(json.dumps({"type": "tts", "state": "stop"}))
        codec.assert_called_once_with([b"fake-opus-frame"], 24000)
        self.assertEqual(self.sent[-1][1]["message"][0]["type"], "record")
        session.conn.plugin_runtime.record_sent.assert_called_once()
        self.assertTrue(session.done.is_set())

    async def test_proactive_is_scoped_recorded_and_refuses_busy_session(self):
        await self.post(event())
        await self.drain()
        session = self.bridge.sessions["alice"]
        await session.send_proactive("下班了吗？")
        self.assertEqual(self.sent[-1][1]["user_id"], 200001)
        self.assertEqual(session.conn.dialogue.dialogue[-1].content, "下班了吗？")
        session.busy = True
        with self.assertRaises(ConnectionError):
            await session.send_proactive("不能打断")
        self.assertEqual(len(self.sent), 2)

    async def test_http_status_does_not_expose_secrets(self):
        self.assertEqual((await self.client.get("/xiaozhi/qq/status")).status, 401)
        response = await self.client.get("/xiaozhi/qq/status", headers={"Authorization": "Bearer " + KEY})
        body = await response.text()
        for secret in (KEY, SECRET, "local-test-token"):
            self.assertNotIn(secret, body)

    async def test_quota_notice_audio_queue_is_delivered_as_text(self):
        session = self.bridge.sessions["alice"]
        await session.connect()
        session.done.clear()
        session.conn.tts.tts_audio_queue.put((SentenceType.LAST, [b"unused-audio"], "今日字数已用完"))
        await asyncio.wait_for(session.done.wait(), 3)
        self.assertEqual(self.sent[-1][1]["message"][0]["data"]["text"], "今日字数已用完")

    async def test_direct_audio_notice_text_fallback_and_clean_bye_close(self):
        session = self.bridge.sessions["alice"]
        await session.connect()
        await session._outgoing(json.dumps({"type": "tts", "state": "sentence_start", "text": "再见"}))
        await session._outgoing(json.dumps({"type": "tts", "state": "stop"}))
        await session.socket.close()
        self.assertTrue(session.reply_finished)
        self.assertEqual(self.sent[-1][1]["message"][0]["data"]["text"], "再见")

    async def test_text_history_reports_only_after_successful_qq_delivery(self):
        session = self.bridge.sessions["alice"]
        await session.connect()
        session.conn.report_tts_enable = True
        reported = Mock()
        with patch.dict(sys.modules, {"core.handle.reportHandle": SimpleNamespace(enqueue_tts_report=reported)}):
            await session._outgoing(json.dumps({"type": "qq_text", "text": "成功发送", "sentence_id": "s1"}))
            reported.assert_called_once_with(session.conn, "成功发送", [])
            self.fail_sends = True
            with self.assertRaises(RuntimeError):
                await session._outgoing(json.dumps({"type": "qq_text", "text": "发送失败", "sentence_id": "s2"}))
            self.assertEqual(reported.call_count, 1)


class MediaAndConfigTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    async def test_real_ffmpeg_decodes_wav_to_16khz_pcm(self):
        data = io.BytesIO()
        with wave.open(data, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(8000)
            writer.writeframes(b"\0\0" * 8000)
        frames = await pcm_audio(data.getvalue())
        self.assertEqual(sum(len(x) for x in frames), 32000)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    async def test_real_ffmpeg_rejects_embedded_file_playlist(self):
        with self.assertRaises(ValueError):
            await pcm_audio(b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:1,\nfile:///etc/passwd\n#EXT-X-ENDLIST\n")

    async def test_config_writer_never_overwrites_existing_file(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("qq_cli", SERVER / "tools/qq_bridge.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / ".qq-bridge.yaml"
            module.write_new_config(target, config())
            original = target.read_bytes()
            with self.assertRaises(FileExistsError):
                module.write_new_config(target, config(self_id="100002"))
            self.assertEqual(target.read_bytes(), original)

    async def test_python310_compatible_syntax(self):
        for source in (SERVER / "core/channels").rglob("*.py"):
            ast.parse(source.read_text(encoding="utf-8"), feature_version=(3, 10))


if __name__ == "__main__":
    unittest.main()
