"""Anthropic Messages API provider for xiaozhi."""

from __future__ import annotations

import copy
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, Iterator, Optional, Sequence

import httpx

from config.logger import setup_logging
from core.providers.llm.base import LLMProviderBase
from core.utils.util import check_model_key

from .protocol import (
    AnthropicProtocolError,
    AnthropicResponseDecoder,
    CachedAssistantTurn,
    ResponseDelta,
    build_headers,
    convert_dialogue,
    convert_tools,
    iter_sse_events,
    iter_utf8_lines,
    normalize_messages_url,
)


TAG = __name__
logger = setup_logging()


class AnthropicMessagesError(RuntimeError):
    """A safe, user-facing provider error."""


@dataclass
class _CacheEntry:
    created_at: float
    turns: "OrderedDict[tuple, CachedAssistantTurn]"


class _SessionTurnCache:
    def __init__(self, ttl_seconds: float, max_sessions: int) -> None:
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.max_sessions = max(1, int(max_sessions))
        self._entries: "OrderedDict[str, _CacheEntry]" = OrderedDict()
        self._lock = threading.Lock()

    def _prune_locked(self, now: float) -> None:
        if self.ttl_seconds == 0:
            self._entries.clear()
            return
        expired = [
            key
            for key, entry in self._entries.items()
            if now - entry.created_at > self.ttl_seconds
        ]
        for key in expired:
            self._entries.pop(key, None)
        while len(self._entries) > self.max_sessions:
            self._entries.popitem(last=False)

    def get(self, session_id: Any):
        key = str(session_id or "")
        if not key:
            return None
        with self._lock:
            now = time.monotonic()
            self._prune_locked(now)
            entry = self._entries.get(key)
            if entry is None:
                return []
            self._entries.move_to_end(key)
            return copy.deepcopy(list(entry.turns.values()))

    def put(self, session_id: Any, turn: CachedAssistantTurn) -> None:
        key = str(session_id or "")
        if not key or self.ttl_seconds == 0:
            return
        with self._lock:
            existing = self._entries.get(key)
            turns = (
                copy.deepcopy(existing.turns)
                if existing is not None
                else OrderedDict()
            )
            turns[turn.tool_ids] = copy.deepcopy(turn)
            turns.move_to_end(turn.tool_ids)
            # A recursive tool chain is normally short.  Keep a defensive
            # per-session bound without discarding earlier turns in the active
            # chain.
            while len(turns) > 32:
                turns.popitem(last=False)
            self._entries[key] = _CacheEntry(
                created_at=time.monotonic(), turns=turns
            )
            self._entries.move_to_end(key)
            self._prune_locked(time.monotonic())

    def delete(self, session_id: Any) -> None:
        key = str(session_id or "")
        if not key:
            return
        with self._lock:
            self._entries.pop(key, None)


def _optional_number(
    config: Dict[str, Any], name: str, converter, default: Any = None
) -> Any:
    value = config.get(name, default)
    if value in (None, ""):
        return default
    try:
        return converter(value)
    except (TypeError, ValueError):
        return default


def _build_timeout(value: Any) -> httpx.Timeout:
    if isinstance(value, dict):
        return httpx.Timeout(
            pool=float(value.get("pool", 2.0)),
            connect=float(value.get("connect", 3.0)),
            write=float(value.get("write", 10.0)),
            read=float(value.get("read", 300.0)),
        )
    if isinstance(value, (int, float)) and value > 0:
        return httpx.Timeout(float(value))
    try:
        numeric = float(value)
        if numeric > 0:
            return httpx.Timeout(numeric)
    except (TypeError, ValueError):
        pass
    return httpx.Timeout(300.0)


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _build_tool_choice(config: Dict[str, Any]) -> Dict[str, Any]:
    """Build a safe Anthropic tool-choice policy.

    Parallel client tools are disabled by default because xiaozhi may resolve
    mixed tool actions over multiple passes.  Users can explicitly override
    this for integrations that guarantee a complete result for every tool id.
    """

    tool_choice: Dict[str, Any] = {
        "type": "auto",
        "disable_parallel_tool_use": True,
    }
    configured = config.get("tool_choice")
    if isinstance(configured, str) and configured.strip():
        try:
            parsed = json.loads(configured)
        except (ValueError, json.JSONDecodeError):
            parsed = {"type": configured.strip()}
        configured = parsed
    if isinstance(configured, dict):
        tool_choice.update(copy.deepcopy(configured))
    if "disable_parallel_tool_use" in config:
        tool_choice["disable_parallel_tool_use"] = _as_bool(
            config.get("disable_parallel_tool_use"), True
        )
    return tool_choice


class LLMProvider(LLMProviderBase):
    """Synchronous streaming provider for Anthropic-compatible Messages APIs."""

    def __init__(self, config: Dict[str, Any]):
        self.model_name = str(config.get("model_name") or "").strip()
        self.api_key = str(config.get("api_key") or "").strip()
        self.url = normalize_messages_url(
            config.get("base_url") or config.get("url") or ""
        )
        if not self.model_name:
            raise ValueError("Anthropic Messages model_name is required")

        self.auth_type = str(config.get("auth_type") or "x-api-key")
        self.anthropic_version = str(
            config.get("anthropic_version") or "2023-06-01"
        )
        self.anthropic_beta = config.get("anthropic_beta")
        self.user_agent = str(
            config.get("user_agent")
            or "xiaozhi-esp32-server/anthropic-messages"
        )
        self.max_tokens = _optional_number(config, "max_tokens", int, 1024)
        if self.max_tokens is None or self.max_tokens < 1:
            self.max_tokens = 1024
        self.temperature = _optional_number(config, "temperature", float)
        self.top_p = _optional_number(config, "top_p", float)
        self.top_k = _optional_number(config, "top_k", int)
        self.tool_choice = _build_tool_choice(config)

        model_key_msg = check_model_key("LLM", self.api_key)
        if model_key_msg:
            logger.bind(tag=TAG).error(model_key_msg)

        self.headers = build_headers(
            api_key=self.api_key,
            auth_type=self.auth_type,
            anthropic_version=self.anthropic_version,
            user_agent=self.user_agent,
            anthropic_beta=self.anthropic_beta,
        )
        self.client = httpx.Client(timeout=_build_timeout(config.get("timeout")))
        self._turn_cache = _SessionTurnCache(
            ttl_seconds=_optional_number(
                config, "thinking_cache_ttl", float, 900.0
            ),
            max_sessions=_optional_number(
                config, "thinking_cache_max_sessions", int, 256
            ),
        )

    def _request_body(
        self,
        dialogue: Sequence[Dict[str, Any]],
        functions: Optional[Sequence[Dict[str, Any]]],
        cached_turns,
        kwargs: Dict[str, Any],
    ):
        converted = convert_dialogue(dialogue, cached_turns=cached_turns)
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        try:
            max_tokens = int(max_tokens)
        except (TypeError, ValueError):
            max_tokens = self.max_tokens
        if max_tokens < 1:
            max_tokens = self.max_tokens

        body: Dict[str, Any] = {
            "model": self.model_name,
            "messages": converted.messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if converted.system:
            body["system"] = converted.system

        optional = {
            "temperature": kwargs.get("temperature", self.temperature),
            "top_p": kwargs.get("top_p", self.top_p),
            "top_k": kwargs.get("top_k", self.top_k),
        }
        for name, value in optional.items():
            if value is not None:
                body[name] = value

        tools = convert_tools(functions)
        if tools:
            body["tools"] = tools
            body["tool_choice"] = copy.deepcopy(self.tool_choice)
        return body, converted

    @staticmethod
    def _safe_error_message(response: httpx.Response, api_key: str) -> str:
        status = response.status_code
        message = ""
        try:
            data = response.json()
            error = data.get("error", {}) if isinstance(data, dict) else {}
            if isinstance(error, dict):
                message = str(error.get("message") or error.get("type") or "")
            elif error:
                message = str(error)
        except (ValueError, json.JSONDecodeError):
            message = ""
        if api_key and message:
            message = message.replace(api_key, "***")
        message = message.replace("\r", " ").replace("\n", " ").strip()[:240]
        suffix = f": {message}" if message else ""
        return f"Anthropic Messages request failed (HTTP {status}){suffix}"

    @staticmethod
    def _tool_namespace(delta) -> SimpleNamespace:
        return SimpleNamespace(
            index=delta.index,
            id=delta.id,
            type="function",
            function=SimpleNamespace(
                name=delta.name,
                arguments=delta.arguments,
            ),
        )

    def _iter_wire_response(
        self,
        body: Dict[str, Any],
        decoder: AnthropicResponseDecoder,
    ) -> Iterator[ResponseDelta]:
        try:
            with self.client.stream(
                "POST", self.url, headers=self.headers, json=body
            ) as response:
                # Explicit UTF-8 avoids locale-dependent decoding on compatible
                # gateways that omit the charset parameter.
                response.encoding = "utf-8"
                if response.status_code >= 400:
                    response.read()
                    raise AnthropicMessagesError(
                        self._safe_error_message(response, self.api_key)
                    )

                content_type = response.headers.get("content-type", "").lower()
                if "text/event-stream" not in content_type:
                    raw = response.read()
                    try:
                        message = json.loads(raw.decode("utf-8-sig"))
                    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                        raise AnthropicMessagesError(
                            "Anthropic Messages returned invalid UTF-8 JSON"
                        ) from exc
                    if not isinstance(message, dict):
                        raise AnthropicMessagesError(
                            "Anthropic Messages JSON response must be an object"
                        )
                    for item in decoder.feed_message(message):
                        yield item
                    return

                for event in iter_sse_events(
                    # iter_bytes first decodes Content-Encoding (gzip/br) but
                    # still returns bytes, so UTF-8 validation remains strict.
                    iter_utf8_lines(response.iter_bytes())
                ):
                    for item in decoder.feed(event):
                        yield item
                if not decoder.completed:
                    raise AnthropicProtocolError(
                        "Anthropic SSE stream ended before message_stop"
                    )
        except AnthropicMessagesError:
            raise
        except AnthropicProtocolError as exc:
            message = str(exc)
            if self.api_key:
                message = message.replace(self.api_key, "***")
            raise AnthropicMessagesError(message[:320]) from exc
        except httpx.HTTPError as exc:
            # Do not include request objects or headers in the public error.
            raise AnthropicMessagesError(
                f"Anthropic Messages network error ({type(exc).__name__})"
            ) from exc

    def _generate(
        self,
        session_id: Any,
        dialogue: Sequence[Dict[str, Any]],
        functions: Optional[Sequence[Dict[str, Any]]],
        **kwargs,
    ) -> Iterator[ResponseDelta]:
        cached_turns = self._turn_cache.get(session_id)
        body, converted = self._request_body(
            dialogue, functions, cached_turns, kwargs
        )
        decoder = AnthropicResponseDecoder()
        finished_normally = False
        try:
            for item in self._iter_wire_response(body, decoder):
                yield item
            finished_normally = decoder.completed
        finally:
            if finished_normally:
                next_turn = decoder.cached_assistant_turn()
                if next_turn is not None:
                    self._turn_cache.put(session_id, next_turn)
                else:
                    # Clear both consumed and abandoned tool continuations.
                    self._turn_cache.delete(session_id)
            elif converted.cached_turn_used:
                # Keep the cached turn for a safe retry after a transient error.
                pass

    def response(self, session_id, dialogue, **kwargs):
        stream = self._generate(session_id, dialogue, None, **kwargs)
        try:
            for item in stream:
                if item.tool_call is not None:
                    self._turn_cache.delete(session_id)
                    raise AnthropicMessagesError(
                        "Anthropic returned tool_use in text-only mode; "
                        "enable function-call intent and use response_with_functions"
                    )
                if item.text:
                    yield item.text
        finally:
            stream.close()

    def response_with_functions(
        self, session_id, dialogue, functions=None, **kwargs
    ):
        for item in self._generate(
            session_id, dialogue, functions, **kwargs
        ):
            if item.text is not None:
                yield item.text, None
            elif item.tool_call is not None:
                yield None, [self._tool_namespace(item.tool_call)]
