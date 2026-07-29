import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "main" / "xiaozhi-server"
sys.path.insert(0, str(SERVER_ROOT))

from core.providers.llm.anthropic_messages.protocol import (  # noqa: E402
    AnthropicProtocolError,
    AnthropicResponseDecoder,
    CachedAssistantTurn,
    build_headers,
    convert_dialogue,
    convert_tools,
    iter_sse_events,
    iter_utf8_lines,
    normalize_messages_url,
)


FIXTURES = Path(__file__).parent / "fixtures" / "anthropic_messages"


class ProtocolConversionTests(unittest.TestCase):
    def test_normalize_url_variants(self):
        expected = "https://api.example.test/v1/messages"
        self.assertEqual(normalize_messages_url("https://api.example.test"), expected)
        self.assertEqual(normalize_messages_url("https://api.example.test/v1"), expected)
        self.assertEqual(
            normalize_messages_url("https://api.example.test/v1/messages/"), expected
        )
        self.assertEqual(
            normalize_messages_url("https://api.example.test/gateway"),
            "https://api.example.test/gateway/v1/messages",
        )

    def test_auth_headers_support_both_modes(self):
        x_key = build_headers("secret", "x_api_key", user_agent="curl/8.5.0")
        self.assertEqual(x_key["x-api-key"], "secret")
        self.assertNotIn("authorization", x_key)
        self.assertEqual(x_key["user-agent"], "curl/8.5.0")

        bearer = build_headers("secret", "bearer")
        self.assertEqual(bearer["authorization"], "Bearer secret")
        self.assertNotIn("x-api-key", bearer)

    def test_tools_and_dialogue_conversion(self):
        tools = convert_tools(
            [
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
        )
        self.assertEqual(tools[0]["input_schema"]["type"], "object")

        cached = CachedAssistantTurn(
            content=[
                {
                    "type": "thinking",
                    "thinking": "hidden",
                    "signature": "opaque-signature",
                },
                {
                    "type": "redacted_thinking",
                    "data": "opaque-redacted",
                },
                {
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "get_weather",
                    "input": {"city": "广州"},
                },
            ],
            tool_ids=("call-1",),
        )
        converted = convert_dialogue(
            [
                {"role": "system", "content": "你是助手"},
                {"role": "user", "content": "天气怎样？"},
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call-1",
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
                    "tool_call_id": "call-1",
                    "content": "晴朗",
                },
            ],
            cached_turn=cached,
        )
        self.assertEqual(converted.system, "你是助手")
        self.assertTrue(converted.cached_turn_used)
        self.assertEqual(converted.messages[1]["content"], cached.content)
        self.assertEqual(
            converted.messages[2]["content"][0],
            {
                "type": "tool_result",
                "tool_use_id": "call-1",
                "content": "晴朗",
            },
        )

    def test_leading_xiaozhi_assistant_welcome_is_ignored(self):
        converted = convert_dialogue(
            [
                {"role": "system", "content": "你是助手"},
                {"role": "assistant", "content": "我在这里哦！"},
                {"role": "assistant", "content": "有什么可以帮你？"},
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好呀"},
                {"role": "user", "content": "今天星期几？"},
            ]
        )

        self.assertEqual(converted.system, "你是助手")
        self.assertEqual(
            [message["role"] for message in converted.messages],
            ["user", "assistant", "user"],
        )
        self.assertEqual(
            converted.messages[0]["content"],
            [{"type": "text", "text": "你好"}],
        )
        self.assertEqual(
            converted.messages[1]["content"],
            [{"type": "text", "text": "你好呀"}],
        )
        all_text = "".join(
            str(block.get("text") or "")
            for message in converted.messages
            for block in message["content"]
        )
        self.assertNotIn("我在这里哦", all_text)
        self.assertNotIn("有什么可以帮你", all_text)

    def test_leading_assistant_tool_turn_is_not_silently_discarded(self):
        with self.assertRaisesRegex(ValueError, "must start with a user"):
            convert_dialogue(
                [
                    {
                        "role": "assistant",
                        "content": "我先调用工具",
                        "tool_calls": [
                            {
                                "id": "orphan-call",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city":"广州"}',
                                },
                            }
                        ],
                    },
                    {"role": "user", "content": "你好"},
                ]
            )

    def test_malformed_leading_assistant_tool_turn_is_not_discarded(self):
        with self.assertRaisesRegex(ValueError, "must start with a user"):
            convert_dialogue(
                [
                    {
                        "role": "assistant",
                        "content": "格式错误的工具调用",
                        "tool_calls": [
                            {
                                "id": "malformed-call",
                                "type": "function",
                                "function": {"arguments": "{}"},
                            }
                        ],
                    },
                    {"role": "user", "content": "你好"},
                ]
            )

    def test_cached_turn_replaces_contiguous_assistant_text_segment(self):
        cached = CachedAssistantTurn(
            content=[
                {
                    "type": "thinking",
                    "thinking": "hidden",
                    "signature": "signature",
                },
                {"type": "text", "text": "我帮你查一下。"},
                {
                    "type": "tool_use",
                    "id": "call-duplicate",
                    "name": "get_weather",
                    "input": {"city": "广州"},
                },
            ],
            tool_ids=("call-duplicate",),
        )
        converted = convert_dialogue(
            [
                {"role": "user", "content": "天气怎样？"},
                {"role": "assistant", "content": "我帮你查一下。"},
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call-duplicate",
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
                    "tool_call_id": "call-duplicate",
                    "content": "晴朗",
                },
            ],
            cached_turns=[cached],
        )
        assistant_blocks = converted.messages[1]["content"]
        text_blocks = [
            block for block in assistant_blocks if block.get("type") == "text"
        ]
        self.assertEqual(text_blocks, [{"type": "text", "text": "我帮你查一下。"}])

    def test_partial_cached_parallel_tool_results_are_rejected(self):
        cached = CachedAssistantTurn(
            content=[
                {
                    "type": "thinking",
                    "thinking": "hidden",
                    "signature": "parallel-signature",
                },
                {
                    "type": "tool_use",
                    "id": "call-a",
                    "name": "tool_a",
                    "input": {},
                },
                {
                    "type": "tool_use",
                    "id": "call-b",
                    "name": "tool_b",
                    "input": {},
                },
            ],
            tool_ids=("call-a", "call-b"),
        )
        with self.assertRaisesRegex(AnthropicProtocolError, "incomplete"):
            convert_dialogue(
                [
                    {"role": "user", "content": "并行调用"},
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call-a",
                                "function": {
                                    "name": "tool_a",
                                    "arguments": "{}",
                                },
                            },
                            {
                                "id": "call-b",
                                "function": {
                                    "name": "tool_b",
                                    "arguments": "{}",
                                },
                            },
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call-a",
                        "content": "only one result",
                    },
                ],
                cached_turns=[cached],
            )
        with self.assertRaisesRegex(AnthropicProtocolError, "incomplete"):
            convert_dialogue(
                [
                    {"role": "user", "content": "混合Action只保留一个工具"},
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call-a",
                                "function": {
                                    "name": "tool_a",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call-a",
                        "content": "only one retained result",
                    },
                ],
                cached_turns=[cached],
            )


class StreamingDecoderTests(unittest.TestCase):
    def test_thinking_is_hidden_and_tool_indexes_are_dense(self):
        lines = (FIXTURES / "mixed_stream.sse").read_bytes().splitlines()
        decoder = AnthropicResponseDecoder()
        output = []
        for event in iter_sse_events(lines):
            output.extend(decoder.feed(event))

        self.assertTrue(decoder.completed)
        self.assertEqual(
            "".join(item.text or "" for item in output),
            "你好，世界",
        )
        tool_fragments = [
            item.tool_call for item in output if item.tool_call is not None
        ]
        self.assertEqual({item.index for item in tool_fragments}, {0, 1})
        weather_args = "".join(
            item.arguments for item in tool_fragments if item.index == 0
        )
        music_args = "".join(
            item.arguments for item in tool_fragments if item.index == 1
        )
        self.assertEqual(json.loads(weather_args), {"city": "广州"})
        self.assertEqual(json.loads(music_args), {"song": "晴天"})

        cached = decoder.cached_assistant_turn()
        self.assertIsNotNone(cached)
        self.assertEqual(cached.tool_ids, ("tool-weather", "tool-music"))
        thinking = next(
            block for block in cached.content if block["type"] == "thinking"
        )
        self.assertEqual(thinking["signature"], "sig-secret")
        self.assertIn("不应该朗读", thinking["thinking"])
        self.assertTrue(
            any(block["type"] == "redacted_thinking" for block in cached.content)
        )

    def test_regular_json_response_only_surfaces_text(self):
        decoder = AnthropicResponseDecoder()
        message = json.loads(
            (FIXTURES / "final_message.json.fixture").read_text(encoding="utf-8")
        )
        output = decoder.feed_message(message)
        self.assertEqual([item.text for item in output], ["广州今天晴朗。"])
        self.assertTrue(decoder.completed)
        self.assertFalse(decoder.has_tool_use)

    def test_invalid_utf8_is_rejected_without_echoing_payload(self):
        with self.assertRaisesRegex(AnthropicProtocolError, "UTF-8"):
            list(iter_sse_events([b"data: \xff", b""]))

    def test_incremental_utf8_decoder_handles_split_codepoints_strictly(self):
        encoded = 'data: {"text":"广州"}\n\n'.encode("utf-8")
        split_at = encoded.index("广".encode("utf-8")) + 1
        lines = list(iter_utf8_lines([encoded[:split_at], encoded[split_at:]]))
        self.assertEqual(lines, ['data: {"text":"广州"}', ""])
        with self.assertRaisesRegex(AnthropicProtocolError, "UTF-8"):
            list(iter_utf8_lines([b"data: \xe5", b"\xff\n"]))

    def test_delta_requires_an_open_content_block(self):
        decoder = AnthropicResponseDecoder()
        with self.assertRaisesRegex(AnthropicProtocolError, "before start"):
            decoder.feed(
                {
                    "type": "content_block_delta",
                    "index": 9,
                    "delta": {"type": "text_delta", "text": "unsafe"},
                }
            )
        decoder.feed(
            {
                "type": "content_block_start",
                "index": 2,
                "content_block": {"type": "text", "text": ""},
            }
        )
        decoder.feed({"type": "content_block_stop", "index": 2})
        with self.assertRaisesRegex(AnthropicProtocolError, "after stop"):
            decoder.feed(
                {
                    "type": "content_block_delta",
                    "index": 2,
                    "delta": {"type": "text_delta", "text": "unsafe"},
                }
            )

    def test_tool_input_in_start_must_be_an_object(self):
        decoder = AnthropicResponseDecoder()
        with self.assertRaisesRegex(AnthropicProtocolError, "must be an object"):
            decoder.feed(
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "bad-input",
                        "name": "get_weather",
                        "input": '{"city":"广州"}',
                    },
                }
            )

    def test_invalid_or_truncated_tool_input_is_rejected(self):
        decoder = AnthropicResponseDecoder()
        decoder.feed(
            {
                "type": "content_block_start",
                "index": 4,
                "content_block": {
                    "type": "tool_use",
                    "id": "bad-tool",
                    "name": "dangerous_tool",
                    "input": {},
                },
            }
        )
        decoder.feed(
            {
                "type": "content_block_delta",
                "index": 4,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"incomplete":',
                },
            }
        )
        with self.assertRaisesRegex(AnthropicProtocolError, "invalid JSON"):
            decoder.feed({"type": "content_block_stop", "index": 4})

    def test_non_tool_stop_reasons_reject_tool_call(self):
        for reason in (
            "max_tokens",
            "model_context_window_exceeded",
            "end_turn",
        ):
            with self.subTest(reason=reason):
                decoder = AnthropicResponseDecoder()
                decoder.feed(
                    {
                        "type": "content_block_start",
                        "index": 1,
                        "content_block": {
                            "type": "tool_use",
                            "id": "truncated-tool",
                            "name": "get_weather",
                            "input": {},
                        },
                    }
                )
                decoder.feed({"type": "content_block_stop", "index": 1})
                with self.assertRaisesRegex(AnthropicProtocolError, reason):
                    decoder.feed(
                        {
                            "type": "message_delta",
                            "delta": {"stop_reason": reason},
                        }
                    )

    def test_json_tool_call_requires_tool_use_stop_reason(self):
        base_message = {
            "type": "message",
            "content": [
                {
                    "type": "tool_use",
                    "id": "json-tool",
                    "name": "get_weather",
                    "input": {"city": "广州"},
                }
            ],
        }
        for reason in ("max_tokens", "model_context_window_exceeded", "end_turn"):
            with self.subTest(reason=reason):
                decoder = AnthropicResponseDecoder()
                with self.assertRaisesRegex(AnthropicProtocolError, reason):
                    decoder.feed_message({**base_message, "stop_reason": reason})

        valid = AnthropicResponseDecoder()
        output = valid.feed_message({**base_message, "stop_reason": "tool_use"})
        self.assertTrue(valid.completed)
        self.assertTrue(any(item.tool_call is not None for item in output))

    def test_message_stop_rejects_unclosed_tool_block(self):
        decoder = AnthropicResponseDecoder()
        decoder.feed(
            {
                "type": "content_block_start",
                "index": 7,
                "content_block": {
                    "type": "tool_use",
                    "id": "unclosed-tool",
                    "name": "get_weather",
                    "input": {},
                },
            }
        )
        decoder.stop_reason = "tool_use"
        with self.assertRaisesRegex(AnthropicProtocolError, "unclosed"):
            decoder.feed({"type": "message_stop"})


if __name__ == "__main__":
    unittest.main()
