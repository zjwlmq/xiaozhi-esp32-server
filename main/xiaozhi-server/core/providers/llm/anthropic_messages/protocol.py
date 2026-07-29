"""Protocol helpers for Anthropic's Messages API.

The rest of xiaozhi uses OpenAI-shaped dialogue and tool-call objects.  This
module keeps the wire-format conversion isolated from the provider so it can be
tested without making network requests.
"""

from __future__ import annotations

import codecs
import copy
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit


class AnthropicProtocolError(RuntimeError):
    """Raised when a Messages response cannot be safely decoded."""


@dataclass(frozen=True)
class ToolCallDelta:
    """One OpenAI-compatible tool-call fragment."""

    index: int
    id: Optional[str] = None
    name: Optional[str] = None
    arguments: str = ""


@dataclass(frozen=True)
class ResponseDelta:
    """A decoded response item.

    Exactly one of ``text`` and ``tool_call`` is normally populated.
    """

    text: Optional[str] = None
    tool_call: Optional[ToolCallDelta] = None


@dataclass(frozen=True)
class CachedAssistantTurn:
    """Assistant content that must be replayed before a tool result."""

    content: List[Dict[str, Any]]
    tool_ids: Tuple[str, ...]


@dataclass(frozen=True)
class ConvertedDialogue:
    system: Optional[str]
    messages: List[Dict[str, Any]]
    cached_turn_used: bool = False


def normalize_messages_url(base_url: str) -> str:
    """Normalize a provider URL to the Anthropic ``/v1/messages`` endpoint."""

    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("Anthropic Messages base_url is required")

    candidate = base_url.strip()
    parts = urlsplit(candidate)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("Anthropic Messages base_url must be an HTTP(S) URL")

    path = parts.path.rstrip("/")
    if path.endswith("/v1/messages"):
        normalized_path = path
    elif path.endswith("/v1"):
        normalized_path = f"{path}/messages"
    else:
        normalized_path = f"{path}/v1/messages"

    return urlunsplit(
        (parts.scheme, parts.netloc, normalized_path or "/v1/messages", parts.query, "")
    )


def build_headers(
    api_key: str,
    auth_type: str = "x-api-key",
    anthropic_version: str = "2023-06-01",
    user_agent: Optional[str] = None,
    anthropic_beta: Optional[str] = None,
) -> Dict[str, str]:
    """Build request headers for official Anthropic or compatible gateways."""

    if not api_key:
        raise ValueError("Anthropic Messages api_key is required")

    normalized_auth = str(auth_type or "x-api-key").strip().lower().replace("_", "-")
    headers = {
        "accept": "text/event-stream, application/json",
        "content-type": "application/json",
        "anthropic-version": anthropic_version or "2023-06-01",
    }
    if normalized_auth in {"x-api-key", "api-key", "apikey"}:
        headers["x-api-key"] = api_key
    elif normalized_auth in {"bearer", "authorization", "auth-token"}:
        headers["authorization"] = f"Bearer {api_key}"
    else:
        raise ValueError(
            "Anthropic Messages auth_type must be x-api-key/x_api_key or bearer"
        )

    if user_agent:
        headers["user-agent"] = str(user_agent)
    if anthropic_beta:
        headers["anthropic-beta"] = str(anthropic_beta)
    return headers


def convert_tools(functions: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Convert OpenAI ``tools`` entries to Anthropic tool definitions."""

    converted: List[Dict[str, Any]] = []
    for item in functions or []:
        function = item.get("function", {}) if isinstance(item, dict) else {}
        name = function.get("name")
        if not name:
            continue
        schema = function.get("parameters")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        tool = {
            "name": str(name),
            "description": str(function.get("description") or ""),
            "input_schema": copy.deepcopy(schema),
        }
        converted.append(tool)
    return converted


def _text_from_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content)


def _parse_tool_arguments(arguments: Any) -> Dict[str, Any]:
    if isinstance(arguments, dict):
        return copy.deepcopy(arguments)
    if arguments in (None, ""):
        return {}
    try:
        parsed = json.loads(str(arguments))
    except (TypeError, ValueError, json.JSONDecodeError):
        # The wire protocol requires an object.  Preserve malformed arguments
        # in a named field rather than emitting invalid JSON.
        return {"_raw_arguments": str(arguments)}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _tool_calls_from_message(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for call in message.get("tool_calls") or []:
        if isinstance(call, dict):
            function = call.get("function") or {}
            call_id = call.get("id")
        else:
            function = getattr(call, "function", None)
            call_id = getattr(call, "id", None)
            if function is not None and not isinstance(function, dict):
                function = {
                    "name": getattr(function, "name", None),
                    "arguments": getattr(function, "arguments", None),
                }
        if not isinstance(function, dict) or not function.get("name"):
            continue
        result.append(
            {
                "type": "tool_use",
                "id": str(call_id or ""),
                "name": str(function["name"]),
                "input": _parse_tool_arguments(function.get("arguments")),
            }
        )
    return result


def _append_message(
    messages: List[Dict[str, Any]], role: str, content: List[Dict[str, Any]]
) -> None:
    if not content:
        return
    # Anthropic accepts multiple content blocks in one turn.  Merging adjacent
    # turns also keeps tool_result blocks in the expected user turn.
    if messages and messages[-1]["role"] == role:
        messages[-1]["content"].extend(content)
    else:
        messages.append({"role": role, "content": content})


def convert_dialogue(
    dialogue: Sequence[Dict[str, Any]],
    cached_turn: Optional[CachedAssistantTurn] = None,
    cached_turns: Optional[Sequence[CachedAssistantTurn]] = None,
) -> ConvertedDialogue:
    """Convert xiaozhi/OpenAI dialogue to Anthropic Messages format.

    A cached assistant turn is used only when its tool ids match an assistant
    tool-call message and the dialogue contains the corresponding tool result.
    This prevents hidden thinking/signature blocks from leaking into unrelated
    requests in the same session.
    """

    system_parts: List[str] = []
    messages: List[Dict[str, Any]] = []
    cached_turn_used = False
    available_cached_turns = list(cached_turns or [])
    if cached_turn is not None:
        available_cached_turns.append(cached_turn)
    tool_result_ids = {
        str(message.get("tool_call_id"))
        for message in dialogue
        if isinstance(message, dict)
        and message.get("role") == "tool"
        and message.get("tool_call_id")
    }
    assistant_tool_id_sets = []
    for message in dialogue:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        assistant_ids = {
            str(block["id"])
            for block in _tool_calls_from_message(message)
            if block.get("id")
        }
        if assistant_ids:
            assistant_tool_id_sets.append(frozenset(assistant_ids))

    # A signed cached assistant turn is atomic.  In mixed Action handling,
    # xiaozhi may retain only the REQLLM subset of a parallel tool response.
    # Any overlap with a cached turn therefore requires the complete original
    # assistant id set and a result for every id.
    historical_ids = set(tool_result_ids)
    for assistant_ids in assistant_tool_id_sets:
        historical_ids.update(assistant_ids)
    for turn in available_cached_turns:
        cached_ids = frozenset(turn.tool_ids)
        if not cached_ids or not cached_ids.intersection(historical_ids):
            continue
        has_complete_assistant_turn = any(
            assistant_ids == cached_ids for assistant_ids in assistant_tool_id_sets
        )
        has_all_results = cached_ids.issubset(tool_result_ids)
        if not has_complete_assistant_turn or not has_all_results:
            raise AnthropicProtocolError(
                "Cached Anthropic tool turn is incomplete in dialogue history; "
                "refusing to replay signed assistant content"
            )

    cached_by_tool_ids = {
        frozenset(turn.tool_ids): turn
        for turn in available_cached_turns
        if turn.tool_ids
    }

    for message in dialogue:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role in {"system", "developer"}:
            text = _text_from_content(message.get("content"))
            if text:
                system_parts.append(text)
            continue

        if role == "assistant":
            blocks: List[Dict[str, Any]] = []
            text = _text_from_content(message.get("content"))
            if text:
                blocks.append({"type": "text", "text": text})

            tool_blocks = _tool_calls_from_message(message)
            # xiaozhi can play a local wake-up greeting and persist it as an
            # assistant message before the user has spoken.  It is not a model
            # turn and Anthropic conversations must start with a user message,
            # so omit only this leading text-only preamble.  A leading
            # assistant tool turn remains an error because dropping it would
            # orphan tool results and could break a signed thinking chain.
            if (
                not messages
                and not message.get("tool_calls")
                and not tool_blocks
            ):
                continue
            tool_ids = tuple(block["id"] for block in tool_blocks if block.get("id"))
            matching_cached_turn = cached_by_tool_ids.get(frozenset(tool_ids))
            if matching_cached_turn is not None and tool_ids:
                returned_tool_ids = {
                    tool_id for tool_id in tool_ids if tool_id in tool_result_ids
                }
                if returned_tool_ids and len(returned_tool_ids) != len(tool_ids):
                    raise AnthropicProtocolError(
                        "Cached Anthropic tool turn has only partial tool results; "
                        "refusing to replay signed assistant content"
                    )
            can_replay_cached = (
                matching_cached_turn is not None
                and tool_ids
                and all(tool_id in tool_result_ids for tool_id in tool_ids)
            )
            if can_replay_cached:
                # xiaozhi may persist text streamed before a tool call as one
                # assistant message and persist tool_calls as the immediately
                # following assistant message.  The cached Anthropic turn
                # already contains both text and tool_use blocks, so replace
                # that whole contiguous assistant segment instead of merging
                # and duplicating the spoken text.
                if messages and messages[-1]["role"] == "assistant":
                    messages.pop()
                blocks = copy.deepcopy(matching_cached_turn.content)
                cached_turn_used = True
            else:
                blocks.extend(tool_blocks)
            _append_message(messages, "assistant", blocks)
            continue

        if role == "tool":
            tool_use_id = message.get("tool_call_id")
            if not tool_use_id:
                continue
            block = {
                "type": "tool_result",
                "tool_use_id": str(tool_use_id),
                "content": _text_from_content(message.get("content")),
            }
            _append_message(messages, "user", [block])
            continue

        if role == "user":
            text = _text_from_content(message.get("content"))
            if text:
                _append_message(messages, "user", [{"type": "text", "text": text}])

    if not messages:
        raise ValueError("Anthropic Messages request requires at least one message")
    if messages[0]["role"] != "user":
        raise ValueError("Anthropic Messages conversation must start with a user message")

    return ConvertedDialogue(
        system="\n\n".join(system_parts) if system_parts else None,
        messages=messages,
        cached_turn_used=cached_turn_used,
    )


def iter_sse_events(lines: Iterable[Any]) -> Iterator[Dict[str, Any]]:
    """Decode UTF-8 SSE lines into JSON events.

    A number of compatible gateways return a regular JSON object even when
    ``stream=true``.  A bare JSON line is therefore accepted as a fallback.
    """

    data_lines: List[str] = []

    def flush() -> Optional[Dict[str, Any]]:
        if not data_lines:
            return None
        raw = "\n".join(data_lines).strip()
        data_lines.clear()
        if not raw or raw == "[DONE]":
            return None
        try:
            decoded = json.loads(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            raise AnthropicProtocolError("Invalid JSON in Anthropic SSE event") from exc
        if not isinstance(decoded, dict):
            raise AnthropicProtocolError("Anthropic SSE event must be a JSON object")
        return decoded

    for raw_line in lines:
        if isinstance(raw_line, bytes):
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise AnthropicProtocolError(
                    "Anthropic SSE response is not valid UTF-8"
                ) from exc
        else:
            line = str(raw_line)
        line = line.rstrip("\r\n")

        if line == "":
            event = flush()
            if event is not None:
                yield event
            continue
        if line.startswith(":") or line.startswith("event:") or line.startswith("id:"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
            continue

        # JSON fallback for gateways that incorrectly keep an SSE content type.
        if not data_lines and line.lstrip().startswith("{"):
            try:
                decoded = json.loads(line)
            except (ValueError, json.JSONDecodeError) as exc:
                raise AnthropicProtocolError(
                    "Invalid JSON in Anthropic response"
                ) from exc
            if not isinstance(decoded, dict):
                raise AnthropicProtocolError(
                    "Anthropic response must be a JSON object"
                )
            yield decoded

    event = flush()
    if event is not None:
        yield event


def iter_utf8_lines(chunks: Iterable[bytes]) -> Iterator[str]:
    """Strictly decode arbitrarily chunked UTF-8 bytes into SSE lines."""

    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    buffer = ""
    try:
        for chunk in chunks:
            if not isinstance(chunk, (bytes, bytearray)):
                raise AnthropicProtocolError(
                    "Anthropic SSE raw stream yielded a non-bytes chunk"
                )
            buffer += decoder.decode(bytes(chunk), final=False)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                yield line
        buffer += decoder.decode(b"", final=True)
    except UnicodeDecodeError as exc:
        raise AnthropicProtocolError(
            "Anthropic SSE response is not valid UTF-8"
        ) from exc
    if buffer:
        yield buffer


class AnthropicResponseDecoder:
    """Stateful Anthropic SSE/JSON decoder."""

    def __init__(self) -> None:
        self._blocks: Dict[int, Dict[str, Any]] = {}
        self._tool_index_by_block: Dict[int, int] = {}
        self._tool_partial_json: Dict[int, str] = {}
        self._tool_had_delta: set[int] = set()
        self._open_blocks: set[int] = set()
        self.completed = False
        self.stop_reason: Optional[str] = None

    @property
    def has_tool_use(self) -> bool:
        return any(block.get("type") == "tool_use" for block in self._blocks.values())

    def cached_assistant_turn(self) -> Optional[CachedAssistantTurn]:
        if not self.completed or not self.has_tool_use:
            return None
        content = [
            copy.deepcopy(self._blocks[index]) for index in sorted(self._blocks.keys())
        ]
        tool_ids = tuple(
            str(block.get("id"))
            for block in content
            if block.get("type") == "tool_use" and block.get("id")
        )
        if not tool_ids:
            return None
        return CachedAssistantTurn(content=content, tool_ids=tool_ids)

    def _dense_tool_index(self, block_index: int) -> int:
        if block_index not in self._tool_index_by_block:
            self._tool_index_by_block[block_index] = len(self._tool_index_by_block)
        return self._tool_index_by_block[block_index]

    def _validate_tool_stop_reason(self) -> None:
        if self.has_tool_use and self.stop_reason != "tool_use":
            reason = self.stop_reason or "missing"
            raise AnthropicProtocolError(
                "Anthropic tool call did not finish with stop_reason=tool_use "
                f"(received {reason})"
            )

    def _start_block(
        self, block_index: int, block: Dict[str, Any]
    ) -> List[ResponseDelta]:
        if not isinstance(block, dict):
            raise AnthropicProtocolError(
                "Anthropic content block must be a JSON object"
            )
        if block_index in self._open_blocks:
            raise AnthropicProtocolError(
                "Anthropic content block started more than once"
            )
        self._open_blocks.add(block_index)
        stored = copy.deepcopy(block)
        block_type = stored.get("type")
        if block_type == "thinking":
            stored.setdefault("thinking", "")
        elif block_type == "text":
            stored.setdefault("text", "")
        elif block_type == "tool_use":
            if "input" in stored and not isinstance(stored["input"], dict):
                raise AnthropicProtocolError(
                    "Anthropic tool input in content_block_start must be an object"
                )
            stored.setdefault("input", {})
            self._tool_partial_json[block_index] = ""
        self._blocks[block_index] = stored

        if block_type != "tool_use":
            return []
        dense_index = self._dense_tool_index(block_index)
        return [
            ResponseDelta(
                tool_call=ToolCallDelta(
                    index=dense_index,
                    id=str(stored.get("id") or ""),
                    name=str(stored.get("name") or ""),
                    arguments="",
                )
            )
        ]

    def _delta_block(
        self, block_index: int, delta: Dict[str, Any]
    ) -> List[ResponseDelta]:
        if block_index not in self._open_blocks:
            raise AnthropicProtocolError(
                "Anthropic content block delta received before start or after stop"
            )
        delta_type = delta.get("type")
        block = self._blocks[block_index]

        if delta_type == "thinking_delta":
            block["thinking"] = str(block.get("thinking") or "") + str(
                delta.get("thinking") or ""
            )
            return []
        if delta_type == "signature_delta":
            block["signature"] = str(block.get("signature") or "") + str(
                delta.get("signature") or ""
            )
            return []
        if delta_type == "text_delta":
            text = str(delta.get("text") or "")
            block["text"] = str(block.get("text") or "") + text
            return [ResponseDelta(text=text)] if text else []
        if delta_type == "input_json_delta":
            partial = str(delta.get("partial_json") or "")
            self._tool_partial_json[block_index] = (
                self._tool_partial_json.get(block_index, "") + partial
            )
            self._tool_had_delta.add(block_index)
            if not partial:
                return []
            return [
                ResponseDelta(
                    tool_call=ToolCallDelta(
                        index=self._dense_tool_index(block_index),
                        arguments=partial,
                    )
                )
            ]
        # ping, citations and future delta types are intentionally not surfaced.
        return []

    def _stop_block(self, block_index: int) -> List[ResponseDelta]:
        if block_index not in self._open_blocks:
            raise AnthropicProtocolError(
                "Anthropic content block stopped without being started"
            )
        block = self._blocks.get(block_index, {})
        if block.get("type") != "tool_use":
            self._open_blocks.discard(block_index)
            return []

        partial = self._tool_partial_json.get(block_index, "")
        if partial:
            try:
                parsed = json.loads(partial)
            except (ValueError, json.JSONDecodeError) as exc:
                raise AnthropicProtocolError(
                    "Anthropic tool input ended with invalid JSON"
                ) from exc
            if not isinstance(parsed, dict):
                raise AnthropicProtocolError(
                    "Anthropic tool input must decode to a JSON object"
                )
            block["input"] = parsed if isinstance(parsed, dict) else {"value": parsed}
            self._open_blocks.discard(block_index)
            return []

        # Some compatible gateways put the complete input in
        # content_block_start and never emit input_json_delta.
        if block_index not in self._tool_had_delta:
            initial_input = block.get("input")
            if initial_input not in (None, {}, ""):
                arguments = json.dumps(
                    initial_input, ensure_ascii=False, separators=(",", ":")
                )
                self._open_blocks.discard(block_index)
                return [
                    ResponseDelta(
                        tool_call=ToolCallDelta(
                            index=self._dense_tool_index(block_index),
                            arguments=arguments,
                        )
                    )
                ]
        self._open_blocks.discard(block_index)
        return []

    def feed(self, event: Dict[str, Any]) -> List[ResponseDelta]:
        event_type = event.get("type")
        if event_type in {"ping", "message_start"}:
            return []
        if event_type == "message_delta":
            delta = event.get("delta") or {}
            if delta.get("stop_reason"):
                self.stop_reason = str(delta["stop_reason"])
            if self.has_tool_use and self.stop_reason:
                self._validate_tool_stop_reason()
            return []
        if event_type == "content_block_start":
            return self._start_block(
                int(event.get("index", 0)), event.get("content_block") or {}
            )
        if event_type == "content_block_delta":
            return self._delta_block(
                int(event.get("index", 0)), event.get("delta") or {}
            )
        if event_type == "content_block_stop":
            return self._stop_block(int(event.get("index", 0)))
        if event_type == "message_stop":
            if self._open_blocks:
                raise AnthropicProtocolError(
                    "Anthropic stream ended with an unclosed content block"
                )
            self._validate_tool_stop_reason()
            self.completed = True
            return []
        if event_type == "error":
            error = event.get("error") or {}
            error_type = str(error.get("type") or "api_error")
            message = str(error.get("message") or "Unknown streaming error")
            raise AnthropicProtocolError(
                f"Anthropic stream error ({error_type}): {message[:240]}"
            )
        if event_type == "message":
            return self.feed_message(event)
        # Forward compatibility: Anthropic may add new SSE event types.
        return []

    def feed_message(self, message: Dict[str, Any]) -> List[ResponseDelta]:
        if message.get("type") == "error":
            return self.feed(message)
        if message.get("type") not in {None, "message"}:
            raise AnthropicProtocolError("Unexpected Anthropic JSON response type")

        output: List[ResponseDelta] = []
        for index, original_block in enumerate(message.get("content") or []):
            if not isinstance(original_block, dict):
                continue
            block = copy.deepcopy(original_block)
            block_type = block.get("type")
            if block_type == "text":
                self._blocks[index] = block
                text = str(block.get("text") or "")
                if text:
                    output.append(ResponseDelta(text=text))
            elif block_type in {"thinking", "redacted_thinking"}:
                self._blocks[index] = block
            elif block_type == "tool_use":
                output.extend(self._start_block(index, block))
                output.extend(self._stop_block(index))
        self.stop_reason = message.get("stop_reason")
        self._validate_tool_stop_reason()
        self.completed = True
        return output
