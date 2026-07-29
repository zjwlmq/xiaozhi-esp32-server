import gzip
import json
import sys
import types
import unittest
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "main" / "xiaozhi-server"
sys.path.insert(0, str(SERVER_ROOT))


class _DummyLogger:
    def bind(self, **kwargs):
        return self

    def error(self, *args, **kwargs):
        return None


# Keep provider unit tests independent from the server's logging/audio runtime.
logger_module = types.ModuleType("config.logger")
logger_module.setup_logging = lambda *args, **kwargs: _DummyLogger()
sys.modules.setdefault("config.logger", logger_module)

base_module = types.ModuleType("core.providers.llm.base")
base_module.LLMProviderBase = object
sys.modules.setdefault("core.providers.llm.base", base_module)

util_module = types.ModuleType("core.utils.util")
util_module.check_model_key = lambda *args, **kwargs: None
sys.modules.setdefault("core.utils.util", util_module)

from core.providers.llm.anthropic_messages.anthropic_messages import (  # noqa: E402
    AnthropicMessagesError,
    LLMProvider,
)


FIXTURES = Path(__file__).parent / "fixtures" / "anthropic_messages"


def _config(**overrides):
    config = {
        "type": "anthropic_messages",
        "base_url": "https://relay.example.test",
        "model_name": "deepseek-v4-pro",
        "api_key": "sk-test-secret-value",
        "auth_type": "x-api-key",
        "anthropic_version": "2023-06-01",
        "user_agent": "curl/8.5.0",
        "max_tokens": 1024,
        "temperature": 0.7,
        "timeout": 30,
    }
    config.update(overrides)
    return config


class ProviderTests(unittest.TestCase):
    def _provider_with_handler(self, handler, **config):
        provider = LLMProvider(_config(**config))
        provider.client.close()
        provider.client = httpx.Client(
            transport=httpx.MockTransport(handler), timeout=30
        )
        self.addCleanup(provider.client.close)
        return provider

    def test_sse_request_uses_x_api_key_and_hides_thinking(self):
        fixture = (FIXTURES / "text_stream.sse").read_bytes()
        captured = {}

        def handler(request):
            captured["request"] = request
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=fixture,
            )

        provider = self._provider_with_handler(handler)
        text = "".join(
            provider.response(
                "session-text",
                [
                    {"role": "system", "content": "简短回答"},
                    {"role": "user", "content": "你好"},
                ],
            )
        )
        self.assertEqual(text, "你好，世界")
        self.assertEqual(captured["request"].url.path, "/v1/messages")
        self.assertEqual(
            captured["request"].headers["x-api-key"], "sk-test-secret-value"
        )
        self.assertEqual(captured["request"].headers["user-agent"], "curl/8.5.0")
        self.assertEqual(captured["body"]["system"], "简短回答")
        self.assertEqual(captured["body"]["max_tokens"], 1024)

    def test_empty_cache_limits_fall_back_to_safe_defaults(self):
        provider = LLMProvider(
            _config(
                thinking_cache_ttl=None,
                thinking_cache_max_sessions="",
            )
        )
        self.addCleanup(provider.client.close)
        self.assertEqual(provider._turn_cache.ttl_seconds, 900.0)
        self.assertEqual(provider._turn_cache.max_sessions, 256)

    def test_provider_rejects_invalid_utf8_sse_bytes(self):
        def handler(request):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b"data: \xe5\xff\n\n",
            )

        provider = self._provider_with_handler(handler)
        with self.assertRaisesRegex(AnthropicMessagesError, "UTF-8"):
            list(
                provider.response(
                    "invalid-utf8",
                    [{"role": "user", "content": "你好"}],
                )
            )

    def test_compressed_sse_is_decoded_before_strict_utf8(self):
        fixture = (FIXTURES / "text_stream.sse").read_bytes()

        def handler(request):
            return httpx.Response(
                200,
                headers={
                    "content-type": "text/event-stream",
                    "content-encoding": "gzip",
                },
                content=gzip.compress(fixture),
            )

        provider = self._provider_with_handler(handler)
        result = "".join(
            provider.response(
                "gzip-sse",
                [{"role": "user", "content": "你好"}],
            )
        )
        self.assertEqual(result, "你好，世界")

    def test_text_only_mode_rejects_unexpected_tool_use(self):
        fixture = (FIXTURES / "tool_turn.sse").read_bytes()

        def handler(request):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=fixture,
            )

        provider = self._provider_with_handler(handler)
        with self.assertRaisesRegex(AnthropicMessagesError, "text-only mode"):
            list(
                provider.response(
                    "session-unexpected-tool",
                    [{"role": "user", "content": "调用工具"}],
                )
            )
        self.assertEqual(provider._turn_cache.get("session-unexpected-tool"), [])

    def test_tool_turn_cache_is_replayed_then_cleared(self):
        tool_stream = (FIXTURES / "tool_turn.sse").read_bytes()
        final_json = (FIXTURES / "final_message.json.fixture").read_bytes()
        requests = []

        def handler(request):
            requests.append(json.loads(request.content.decode("utf-8")))
            if len(requests) == 1:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=tool_stream,
                )
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=final_json,
            )

        provider = self._provider_with_handler(handler)
        functions = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "查询天气",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                },
            }
        ]
        first = list(
            provider.response_with_functions(
                "session-tools",
                [{"role": "user", "content": "广州天气"}],
                functions=functions,
            )
        )
        self.assertEqual(
            requests[0]["tool_choice"],
            {"type": "auto", "disable_parallel_tool_use": True},
        )
        tool_fragments = [
            call
            for _, calls in first
            for call in (calls or [])
        ]
        self.assertEqual({call.index for call in tool_fragments}, {0})
        self.assertEqual(
            "".join(call.function.arguments for call in tool_fragments),
            '{"city":"广州"}',
        )
        self.assertEqual(len(provider._turn_cache.get("session-tools")), 1)

        second_dialogue = [
            {"role": "user", "content": "广州天气"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-weather",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city":"广州"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-weather",
                "content": "晴朗",
            },
        ]
        final = "".join(
            provider.response("session-tools", second_dialogue)
        )
        self.assertEqual(final, "广州今天晴朗。")

        replayed_blocks = requests[1]["messages"][1]["content"]
        self.assertEqual(replayed_blocks[0]["type"], "thinking")
        self.assertEqual(replayed_blocks[0]["signature"], "opaque-signature")
        self.assertEqual(replayed_blocks[1]["type"], "redacted_thinking")
        self.assertEqual(replayed_blocks[2]["type"], "tool_use")
        self.assertEqual(replayed_blocks[2]["input"], {"city": "广州"})
        self.assertEqual(provider._turn_cache.get("session-tools"), [])

    def test_multi_step_tool_chain_replays_every_cached_turn(self):
        first_stream = (FIXTURES / "tool_turn.sse").read_bytes()
        second_stream = (FIXTURES / "tool_turn_second.sse").read_bytes()
        final_json = (FIXTURES / "final_message.json.fixture").read_bytes()
        requests = []

        def handler(request):
            requests.append(json.loads(request.content.decode("utf-8")))
            if len(requests) == 1:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=first_stream,
                )
            if len(requests) == 2:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=second_stream,
                )
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=final_json,
            )

        provider = self._provider_with_handler(handler)
        functions = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": name,
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            for name in ("get_weather", "get_air_quality")
        ]
        first_user = {"role": "user", "content": "广州天气和空气质量"}
        first_assistant = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call-weather",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city":"广州"}',
                    },
                }
            ],
        }
        first_result = {
            "role": "tool",
            "tool_call_id": "call-weather",
            "content": "晴朗",
        }
        list(
            provider.response_with_functions(
                "multi-session", [first_user], functions=functions
            )
        )
        list(
            provider.response_with_functions(
                "multi-session",
                [first_user, first_assistant, first_result],
                functions=functions,
            )
        )
        self.assertEqual(len(provider._turn_cache.get("multi-session")), 2)

        second_assistant = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call-air",
                    "type": "function",
                    "function": {
                        "name": "get_air_quality",
                        "arguments": '{"city":"广州"}',
                    },
                }
            ],
        }
        second_result = {
            "role": "tool",
            "tool_call_id": "call-air",
            "content": "优",
        }
        final = "".join(
            provider.response(
                "multi-session",
                [
                    first_user,
                    first_assistant,
                    first_result,
                    second_assistant,
                    second_result,
                ],
            )
        )
        self.assertEqual(final, "广州今天晴朗。")
        assistant_turns = [
            message
            for message in requests[2]["messages"]
            if message["role"] == "assistant"
        ]
        self.assertEqual(
            assistant_turns[0]["content"][0]["signature"],
            "opaque-signature",
        )
        self.assertEqual(
            assistant_turns[1]["content"][0]["signature"],
            "second-signature",
        )
        self.assertEqual(provider._turn_cache.get("multi-session"), [])

    def test_bearer_and_json_fallback(self):
        final_json = (FIXTURES / "final_message.json.fixture").read_bytes()
        captured = {}

        def handler(request):
            captured["headers"] = request.headers
            return httpx.Response(
                200,
                headers={"content-type": "application/json; charset=utf-8"},
                content=final_json,
            )

        provider = self._provider_with_handler(handler, auth_type="bearer")
        result = "".join(
            provider.response("session-json", [{"role": "user", "content": "你好"}])
        )
        self.assertEqual(result, "广州今天晴朗。")
        self.assertEqual(
            captured["headers"]["authorization"],
            "Bearer sk-test-secret-value",
        )

    def test_tool_choice_can_explicitly_override_parallel_safety(self):
        tool_stream = (FIXTURES / "tool_turn.sse").read_bytes()
        captured = {}

        def handler(request):
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=tool_stream,
            )

        provider = self._provider_with_handler(
            handler,
            tool_choice={
                "type": "auto",
                "disable_parallel_tool_use": False,
            },
        )
        list(
            provider.response_with_functions(
                "tool-choice-override",
                [{"role": "user", "content": "天气"}],
                functions=[
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "description": "",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            )
        )
        self.assertEqual(
            captured["body"]["tool_choice"],
            {"type": "auto", "disable_parallel_tool_use": False},
        )

    def test_http_error_does_not_expose_api_key(self):
        secret = "sk-test-secret-value"

        def handler(request):
            return httpx.Response(
                401,
                headers={"content-type": "application/json"},
                json={
                    "type": "error",
                    "error": {
                        "type": "authentication_error",
                        "message": f"Invalid token {secret}",
                    },
                },
            )

        provider = self._provider_with_handler(handler)
        with self.assertRaises(AnthropicMessagesError) as caught:
            list(
                provider.response(
                    "session-error", [{"role": "user", "content": "你好"}]
                )
            )
        self.assertNotIn(secret, str(caught.exception))
        self.assertIn("***", str(caught.exception))

    def test_sse_eof_without_message_stop_is_an_error(self):
        truncated = b"\n".join(
            [
                b"event: content_block_start",
                b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
                b"",
                b"event: content_block_delta",
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"partial"}}',
                b"",
            ]
        )

        def handler(request):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=truncated,
            )

        provider = self._provider_with_handler(handler)
        with self.assertRaisesRegex(AnthropicMessagesError, "message_stop"):
            list(
                provider.response(
                    "session-eof", [{"role": "user", "content": "你好"}]
                )
            )


if __name__ == "__main__":
    unittest.main()
