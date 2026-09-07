import ast
import copy
import importlib.util
import json
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1] / "main" / "xiaozhi-server"
spec = importlib.util.spec_from_file_location("browser_voice_settings", ROOT / "core/utils/voice_settings.py")
settings_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(settings_module)
validate = settings_module.validate_voice_settings
configure = settings_module.configure_voice_settings
build = settings_module.build_voice_parameters


def make_conn():
    return SimpleNamespace(need_bind=False, websocket=SimpleNamespace(send=AsyncMock()), config={
        "selected_module": {"TTS": "clone"},
        "TTS": {"clone": {"type": "huoshan_double_stream", "private_voice": "S_test_voice",
                           "api_key": "must-not-leave-server", "resource_id": "seed-icl-2.0"}},
    })


def defaults():
    return {"resource_id": "seed-icl-2.0", "model": None, "speaker": "S_test_voice",
            "audio_params": {"speech_rate": 7, "loudness_rate": 8, "sample_rate": 24000},
            "additions": {"post_process": {"pitch": -2}, "aigc_metadata": {"producer": "test"},
                          "cache_config": {"enabled": False}}}


def load_provider_methods():
    tree = ast.parse((ROOT / "core/providers/tts/huoshan_double_stream.py").read_text(encoding="utf-8"))
    original = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TTSProvider")
    methods = {"_build_ws_headers", "_apply_browser_voice_settings", "get_payload_bytes"}
    cls = ast.ClassDef(name="Provider", bases=[], keywords=[], decorator_list=[],
                      body=[n for n in original.body if getattr(n, "name", None) in methods])
    namespace = {"uuid": uuid, "json": json, "EVENT_NONE": 0, "build_voice_parameters": build}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(ROOT), "exec"), namespace)
    return namespace["Provider"]


class VoiceSettingsTest(unittest.TestCase):
    def test_server_defaults_are_opt_in(self):
        conn = make_conn()
        result = configure(conn)
        self.assertEqual(result["settings"]["version"], "server")
        self.assertIsNone(conn.browser_tts_settings)

    def test_custom_controls_are_isolated_and_do_not_expose_credentials(self):
        conn, other = make_conn(), make_conn()
        before = copy.deepcopy(conn.config)
        result = configure(conn, {"version": "2.0", "generation": "expressive", "pitch": 4, "speed": 1.3})
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(conn.config, before)
        self.assertFalse(hasattr(other, "browser_tts_settings"))
        self.assertNotIn("must-not-leave-server", json.dumps(result))
        self.assertEqual(result["voice"], "S_test_voice")

    def test_invalid_settings_cannot_replace_last_valid_settings(self):
        bad = [{"version": "9"}, {"api_key": "injected"}, {"speaker": "S_other"},
               {"resource_id": "seed-tts-2.0"}, {"speed": True}, {"speed": float("nan")},
               {"speed": float("inf")}, {"speed": 0.4}, {"speed": 2.1}, {"pitch": True},
               {"pitch": 0.5}, {"pitch": 13}, {"language": "invalid"}, [], "2.0"]
        conn = make_conn()
        configure(conn, {"version": "2.0"})
        old = copy.deepcopy(conn.browser_tts_settings)
        for value in bad:
            with self.subTest(value=value):
                self.assertEqual(configure(conn, value)["status"], "error")
                self.assertEqual(conn.browser_tts_settings, old)

    def test_only_bound_cloned_huoshan_voices_allow_overrides(self):
        for field, value in [("type", "edge"), ("private_voice", "zh_female_stock")]:
            conn = make_conn()
            conn.config["TTS"]["clone"][field] = value
            self.assertEqual(configure(conn, {"version": "2.0"})["status"], "error")
        conn = make_conn()
        conn.need_bind = True
        self.assertEqual(configure(conn, {"version": "2.0"})["status"], "error")

    def test_legacy_generation_is_not_silently_substituted(self):
        with self.assertRaises(ValueError):
            build(defaults(), validate({"version": "1.0", "generation": "restoration"}))
        with self.assertRaises(ValueError):
            validate({"version": "2.0", "generation": "trained"})
        with self.assertRaises(ValueError):
            validate({"version": "2.0", "generation": "restoration"})
        settings = validate({"version": "1.0", "generation": "trained"})
        self.assertEqual(build(defaults(), settings)["resource_id"], "seed-icl-1.0")
        self.assertIsNone(build(defaults(), settings)["model"])

    def test_standard_and_expressive_emit_official_model_ids(self):
        for generation, model in [("standard", "seed-tts-2.0-standard"),
                                  ("expressive", "seed-tts-2.0-expressive")]:
            result = build(defaults(), validate({"version": "2.0", "generation": generation}))
            self.assertEqual(result["model"], model)

    def test_legacy_styles_require_a_variant_of_the_bound_voice(self):
        conn = make_conn()
        variants = {"standard": "S_trained_standard", "restoration": "S_trained_restoration"}
        conn.config["TTS"]["clone"]["browser_voice_variants"] = {
            "S_test_voice": variants, "S_other_agent": {"restoration": "S_other_private_voice"}}
        original = defaults()
        original["variants"] = variants
        original["resource_id"] = "seed-icl-1.0-concurr"
        for style, speaker in variants.items():
            result = configure(conn, {"version": "1.0", "generation": style})
            self.assertEqual(result["status"], "accepted")
            self.assertEqual(result["voice"], speaker)
            parameters = build(original, conn.browser_tts_settings)
            self.assertEqual(parameters["speaker"], speaker)
            self.assertEqual(parameters["resource_id"], "seed-icl-1.0-concurr")
            self.assertIsNone(parameters["model"])
        conn.config["TTS"]["clone"]["browser_voice_variants"].pop("S_test_voice")
        result = configure(conn, {"version": "1.0", "generation": "restoration"})
        self.assertEqual(result["status"], "error")
        self.assertNotIn("S_other_private_voice", json.dumps(result))

    def test_pitch_speed_and_language_preserve_unrelated_audio_fields(self):
        original = defaults()
        before = copy.deepcopy(original)
        result = build(original, validate({"version": "2.0", "speed": 0.5, "pitch": 12, "language": "en"}))
        self.assertEqual(result["audio_params"], {"speech_rate": -50, "loudness_rate": 8, "sample_rate": 24000})
        self.assertEqual(result["additions"]["post_process"]["pitch"], 12)
        self.assertEqual(result["additions"]["explicit_language"], "en")
        self.assertEqual(result["additions"]["aigc_metadata"], before["additions"]["aigc_metadata"])
        self.assertEqual(original, before)
        self.assertEqual(build(original, None), before)

    def test_auto_language_removes_explicit_language_and_speed_max_is_valid(self):
        original = defaults()
        original["additions"]["explicit_language"] = "zh-cn"
        result = build(original, validate({"version": "2.0", "speed": 2, "pitch": -12, "language": "auto"}))
        self.assertNotIn("explicit_language", result["additions"])
        self.assertEqual(result["audio_params"]["speech_rate"], 100)


class VoiceProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_hello_negotiation_and_browser_cache_bypass(self):
        source = ROOT / "core/handle/helloHandle.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        functions = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                     and n.name in ("handleHelloMessage", "checkWakeupWords")]
        namespace = {"json": json, "configure_voice_settings": configure, "TAG": "test"}
        exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])), str(source), "exec"), namespace)
        conn = make_conn()
        conn.welcome_msg = {"type": "hello", "session_id": "test"}
        conn.logger = SimpleNamespace(bind=lambda **_: SimpleNamespace(debug=lambda *_: None))
        await namespace["handleHelloMessage"](conn, {"features": {"voice_settings": True},
                    "voice_settings": {"version": "2.0", "speed": 1.2}})
        reply = json.loads(conn.websocket.send.call_args.args[0])
        self.assertEqual(reply["voice_settings"]["status"], "accepted")
        self.assertEqual(conn.browser_tts_settings["speed"], 1.2)
        self.assertNotIn("voice_settings", conn.welcome_msg)
        configure(conn, {"version": "server"})
        self.assertFalse(await namespace["checkWakeupWords"](conn, "你好"))
        await namespace["handleHelloMessage"](conn, {})
        self.assertNotIn("voice_settings", json.loads(conn.websocket.send.call_args.args[0]))

    def make_provider(self):
        provider = load_provider_methods()()
        provider._voice_defaults = defaults()
        provider.resource_id = "seed-icl-2.0"
        provider.synthesis_model = None
        provider.audio_params = copy.deepcopy(provider._voice_defaults["audio_params"])
        provider.additions = copy.deepcopy(provider._voice_defaults["additions"])
        provider.mix_speaker = {}
        provider.api_key = "test-key"
        provider.conn = make_conn()
        provider.ws = SimpleNamespace(close=AsyncMock())
        provider._cancel_monitor_task = AsyncMock()
        return provider

    async def test_settings_change_at_next_utterance_and_reconnect_for_new_version(self):
        provider = self.make_provider()
        configure(provider.conn, {"version": "2.0", "generation": "expressive", "speed": 1.4, "pitch": 5})
        await provider._apply_browser_voice_settings()
        first = json.loads(provider.get_payload_bytes(text="你好", speaker="S_test_voice"))["req_params"]
        self.assertEqual(first["model"], "seed-tts-2.0-expressive")
        self.assertEqual(first["audio_params"]["speech_rate"], 40)
        self.assertEqual(json.loads(first["additions"])["post_process"]["pitch"], 5)
        provider.ws.close.assert_not_awaited()
        old_ws = provider.ws
        configure(provider.conn, {"version": "1.0", "generation": "trained"})
        # An in-flight utterance retains its model until the next start_session.
        self.assertEqual(json.loads(provider.get_payload_bytes())["req_params"]["model"], first["model"])
        await provider._apply_browser_voice_settings()
        old_ws.close.assert_awaited_once()
        self.assertIsNone(provider.ws)
        self.assertEqual(provider._build_ws_headers()["X-Api-Resource-Id"], "seed-icl-1.0")
        self.assertNotIn("model", json.loads(provider.get_payload_bytes())["req_params"])

    async def test_reset_restores_original_provider_fields(self):
        provider = self.make_provider()
        configure(provider.conn, {"version": "2.0", "speed": 2, "pitch": 12})
        await provider._apply_browser_voice_settings()
        configure(provider.conn, {"version": "server"})
        await provider._apply_browser_voice_settings()
        self.assertEqual(provider.audio_params, defaults()["audio_params"])
        self.assertEqual(provider.additions, defaults()["additions"])
        self.assertIsNone(provider.synthesis_model)

    async def test_protocol_handler_reports_rejection_without_mutating_config(self):
        source = ROOT / "core/handle/textHandler/voiceSettingsMessageHandler.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        cls.bases = []
        namespace = {"json": json, "configure_voice_settings": configure}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(source), "exec"), namespace)
        handler = namespace["VoiceSettingsMessageHandler"]()
        conn = make_conn()
        await handler.handle(conn, {"request_id": "voice-1", "settings": {"version": "2.0", "pitch": 2}})
        result = json.loads(conn.websocket.send.call_args.args[0])
        self.assertEqual(result["request_id"], "voice-1")
        self.assertEqual(result["status"], "accepted")
        await handler.handle(conn, {"request_id": "voice-2", "settings": {"pitch": 99}})
        result = json.loads(conn.websocket.send.call_args.args[0])
        self.assertEqual(result["status"], "error")
        self.assertEqual(conn.browser_tts_settings["pitch"], 2)


if __name__ == "__main__":
    unittest.main()
