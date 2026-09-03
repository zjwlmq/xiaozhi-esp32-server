"""Private, structured continuing-life memory for the Nixi role pack.

Memories are stored below xiaozhi-server/data so the existing Docker data mount
keeps them across upgrades.  The file is scoped by the manager account id, not
by an individual agent or device, which lets wu/chi/duo share one family life.

The LLM may propose memory actions, but deterministic validation controls what
can become history:
* assistant-only content can only create a pending plan;
* facts, completed events, corrections and cancellations require an exact quote
  from a user message;
* a planned date passing never changes its status automatically.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..base import MemoryProviderBase, logger


TAG = __name__
SCHEMA_VERSION = 1
ALLOWED_KINDS = {"user_fact", "preference", "event", "plan", "relationship"}
ALLOWED_VISIBILITY = {"shared", "wu_private", "chi_private"}
ALLOWED_STATUS = {
    "active",
    "pending",
    "planned",
    "completed",
    "cancelled",
    "superseded",
}
ALLOWED_OPERATIONS = {"add", "complete", "cancel", "correct"}
SECRET_MARKERS = (
    "api key",
    "apikey",
    "api密钥",
    "密码",
    "口令",
    "access token",
    "refresh token",
    "authorization",
)
TOKEN_LIKE_RE = re.compile(r"(?:sk|key|token)-[A-Za-z0-9_-]{12,}", re.IGNORECASE)
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")

EXTRACTION_PROMPT = """
你是“持续生活记忆”提取器，不扮演人物。只输出一个 JSON 对象，格式为
{"actions":[...]}，没有值得记住的内容就输出 {"actions":[]}。

每个 action 字段：
operation: add | complete | cancel | correct
target_id: 更新旧记录时填写；add 时为 null
kind: user_fact | preference | event | plan | relationship
visibility: shared | wu_private | chi_private
status: active | pending | planned | completed | cancelled
content: 不超过 120 个汉字的第三人称简述
event_at: 明确日期时间的 ISO-8601 字符串，否则 null
importance: 1 到 5
evidence_role: user | assistant
evidence_quote: 必须逐字摘自本次对话中对应角色的一小段话

硬规则：
1. 用户明确说出的身份、喜好、边界、已经发生的经历、确认或改期可以记录。
2. 人物自己提出、用户尚未接受的约定只能 add plan + pending，不能写成经历。
3. 用户接受未来安排后写 plan + planned；用户明确说已经发生后才可 completed。
4. 日期到了不代表计划完成，不能自行 complete。
5. 玩笑、假设、梦、角色随口编的往事、含糊猜测、密码、密钥、令牌不记录。
6. “好”“行”等回应只有在紧邻的上下文中确实接受了具体安排时才可作为证据。
7. 用户纠正旧记忆用 correct；明确取消计划用 cancel；明确完成计划用 complete。
   已存在 pending 计划而用户后来接受时，必须用 correct + 原 target_id 把它改成 planned，
   不得再 add 一条重复计划。用户在同一次对话里直接接受刚提出的安排时可直接 add planned。
8. 只告诉吴所畏的内容用 wu_private，只告诉池骋的内容用 chi_private；其他家庭生活用 shared。
9. 不因为人物材料、小说或影视内容创建生活记忆。
""".strip()


_LOCKS: Dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _file_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso_now() -> str:
    return _now().isoformat(timespec="seconds")


def _safe_key(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text if SAFE_ID_RE.fullmatch(text) else fallback


def _normalize_text(value: object, limit: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _message_text(content: object) -> str:
    if not isinstance(content, str):
        return ""
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            decoded = json.loads(stripped)
            if isinstance(decoded, dict) and isinstance(decoded.get("content"), str):
                return decoded["content"].strip()
        except (ValueError, TypeError):
            pass
    return stripped


def _contains_secret(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in SECRET_MARKERS) or bool(
        TOKEN_LIKE_RE.search(text)
    )


def _parse_json_object(raw: object) -> Dict[str, Any]:
    if not isinstance(raw, str):
        raise ValueError("memory extractor did not return text")
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("memory extractor did not return a JSON object")
        text = text[start : end + 1]
    decoded = json.loads(text)
    if not isinstance(decoded, dict):
        raise ValueError("memory extractor root must be an object")
    return decoded


class NixiLifeMemoryStore:
    """Atomic JSON store for one account-owned family universe."""

    def __init__(self, storage_dir: Path, owner_id: object, universe_id: object):
        self.owner_id = _safe_key(owner_id, "device-local")
        self.universe_id = _safe_key(universe_id, "nixi-family")
        self.directory = Path(storage_dir).resolve() / self.owner_id
        self.path = self.directory / f"{self.universe_id}.json"
        self.lock = _file_lock(self.path)

    def _empty(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "owner_id": self.owner_id,
            "universe_id": self.universe_id,
            "records": [],
        }

    def load(self) -> Dict[str, Any]:
        with self.lock:
            if not self.path.is_file():
                return self._empty()
            decoded = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(decoded, dict)
                or decoded.get("schema_version") != SCHEMA_VERSION
                or decoded.get("owner_id") != self.owner_id
                or decoded.get("universe_id") != self.universe_id
                or not isinstance(decoded.get("records"), list)
            ):
                raise ValueError(f"invalid nixi memory store: {self.path}")
            return decoded

    def save(self, data: Dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=f".{self.universe_id}.", suffix=".tmp", dir=str(self.directory)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    @staticmethod
    def _evidence_exists(
        role: str, quote: str, messages: Sequence[Tuple[str, str]]
    ) -> bool:
        return any(item_role == role and quote in text for item_role, text in messages)

    def apply_actions(
        self,
        raw_actions: object,
        messages: Sequence[Tuple[str, str]],
        session_id: Optional[str],
        allowed_visibilities: Optional[set] = None,
        allowed_target_ids: Optional[set] = None,
    ) -> int:
        if not isinstance(raw_actions, list):
            return 0
        with self.lock:
            data = self.load()
            records = data["records"]
            by_id = {
                item.get("id"): item
                for item in records
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            applied = 0
            for candidate in raw_actions[:12]:
                action = self._validated_action(
                    candidate,
                    messages,
                    by_id,
                    allowed_visibilities=allowed_visibilities,
                    allowed_target_ids=allowed_target_ids,
                )
                if action is None:
                    continue
                operation = action.pop("operation")
                target_id = action.pop("target_id", None)
                if operation == "add":
                    if self._is_duplicate(records, action):
                        continue
                    records.append(self._new_record(action, session_id))
                elif operation in {"complete", "cancel"}:
                    target = by_id[target_id]
                    target["status"] = "completed" if operation == "complete" else "cancelled"
                    if action.get("event_at"):
                        target["event_at"] = action["event_at"]
                    target["updated_at"] = _iso_now()
                    target["last_user_quote"] = action["evidence_quote"]
                elif operation == "correct":
                    target = by_id[target_id]
                    target["status"] = "superseded"
                    target["updated_at"] = _iso_now()
                    replacement = self._new_record(action, session_id)
                    replacement["supersedes_id"] = target_id
                    records.append(replacement)
                    by_id[replacement["id"]] = replacement
                applied += 1
            if applied:
                self.save(data)
            return applied

    def _validated_action(
        self,
        candidate: object,
        messages: Sequence[Tuple[str, str]],
        by_id: Dict[str, Dict[str, Any]],
        allowed_visibilities: Optional[set] = None,
        allowed_target_ids: Optional[set] = None,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(candidate, dict):
            return None
        operation = str(candidate.get("operation", "")).strip()
        kind = str(candidate.get("kind", "")).strip()
        visibility = str(candidate.get("visibility", "")).strip()
        status = str(candidate.get("status", "")).strip()
        evidence_role = str(candidate.get("evidence_role", "")).strip()
        evidence_quote = _normalize_text(candidate.get("evidence_quote"), 160)
        content = _normalize_text(candidate.get("content"), 240)
        target_id = candidate.get("target_id")
        if target_id is not None:
            target_id = str(target_id).strip()
        try:
            importance = max(1, min(5, int(candidate.get("importance", 3))))
        except (TypeError, ValueError):
            return None
        if (
            operation not in ALLOWED_OPERATIONS
            or kind not in ALLOWED_KINDS
            or visibility not in ALLOWED_VISIBILITY
            or (
                allowed_visibilities is not None
                and visibility not in allowed_visibilities
            )
            or status not in ALLOWED_STATUS
            or evidence_role not in {"user", "assistant"}
            or not content
            or not evidence_quote
            or _contains_secret(content)
            or _contains_secret(evidence_quote)
            or not self._evidence_exists(evidence_role, evidence_quote, messages)
        ):
            return None

        # Model-authored content is never promoted into lived history by itself.
        if evidence_role == "assistant" and not (
            operation == "add" and kind == "plan" and status == "pending"
        ):
            return None
        if operation == "add" and target_id is not None:
            return None
        if operation != "add" and (
            evidence_role != "user"
            or not target_id
            or target_id not in by_id
            or (
                allowed_target_ids is not None
                and target_id not in allowed_target_ids
            )
        ):
            return None
        if operation != "add" and by_id[target_id].get("status") == "superseded":
            return None
        if operation == "complete" and status != "completed":
            return None
        if operation == "cancel" and status != "cancelled":
            return None
        if operation in {"complete", "cancel"}:
            target = by_id[target_id]
            if (
                target.get("kind") != "plan"
                or kind != "plan"
                or visibility != target.get("visibility")
                or target.get("status") not in {"pending", "planned"}
            ):
                return None
        if operation == "correct" and status in {"pending", "superseded"}:
            return None
        if kind == "plan" and operation == "add" and status not in {"pending", "planned"}:
            return None
        if kind != "plan" and operation == "add" and status not in {"active", "completed"}:
            return None

        event_at = candidate.get("event_at")
        if event_at is not None:
            event_at = _normalize_text(str(event_at), 64)
            try:
                datetime.fromisoformat(event_at.replace("Z", "+00:00"))
            except ValueError:
                return None

        return {
            "operation": operation,
            "target_id": target_id,
            "kind": kind,
            "visibility": visibility,
            "status": status,
            "content": content,
            "event_at": event_at,
            "importance": importance,
            "evidence_role": evidence_role,
            "evidence_quote": evidence_quote,
        }

    @staticmethod
    def _new_record(action: Dict[str, Any], session_id: Optional[str]) -> Dict[str, Any]:
        created = _iso_now()
        record = dict(action)
        record.pop("target_id", None)
        record["id"] = uuid.uuid4().hex
        record["pinned"] = False
        record["source_session_id"] = str(session_id or "")[:96]
        record["created_at"] = created
        record["updated_at"] = created
        return record

    @staticmethod
    def _is_duplicate(records: Iterable[Dict[str, Any]], action: Dict[str, Any]) -> bool:
        content_key = re.sub(r"\s+", "", action["content"])
        return any(
            isinstance(item, dict)
            and item.get("kind") == action["kind"]
            and item.get("visibility") == action["visibility"]
            and item.get("status") not in {"cancelled", "superseded"}
            and re.sub(r"\s+", "", str(item.get("content", ""))) == content_key
            for item in records
        )


class MemoryProvider(MemoryProviderBase):
    def __init__(self, config: Dict[str, Any], summary_memory=None):
        super().__init__(config)
        self.context: Dict[str, Any] = {}
        self.store: Optional[NixiLifeMemoryStore] = None
        self.enabled = False
        self.max_context_records = int(config.get("max_context_records", 60))
        self.storage_dir = self._resolve_storage_dir(config.get("storage_dir"))
        self.timezone_name = str(config.get("timezone") or "").strip()
        try:
            self.timezone = ZoneInfo(self.timezone_name) if self.timezone_name else None
        except ZoneInfoNotFoundError:
            self.timezone = None
            logger.bind(tag=TAG).error(
                f"持续生活记忆时区不可用，回退到服务器时区: {self.timezone_name}"
            )

    @staticmethod
    def _resolve_storage_dir(configured: object) -> Path:
        server_root = Path(__file__).resolve().parents[4]
        path = Path(str(configured or "data/nixi_life_memory"))
        return path if path.is_absolute() else server_root / path

    def init_memory(
        self,
        role_id,
        llm,
        nixi_life_context=None,
        **kwargs,
    ):
        super().init_memory(role_id, llm, **kwargs)
        supplied = nixi_life_context if isinstance(nixi_life_context, dict) else {}
        self.context = {
            "owner_id": supplied.get("owner_id") or role_id,
            "universe_id": supplied.get("universe_id") or "nixi-family",
            "mode": supplied.get("mode") or "unknown",
            "agent_id": supplied.get("agent_id") or "",
        }
        self.store = NixiLifeMemoryStore(
            self.storage_dir,
            self.context["owner_id"],
            self.context["universe_id"],
        )
        self.enabled = bool(
            supplied
            and self.context["owner_id"]
            and self.context["mode"] in {"wu", "chi", "duo"}
        )
        if not self.enabled:
            logger.bind(tag=TAG).error(
                "持续生活记忆未启用：当前智能体没有有效的 Nixi 账号/模式上下文"
            )

    def set_llm(self, llm):
        self.llm = llm

    def _current_time(self) -> datetime:
        return datetime.now(self.timezone) if self.timezone else _now()

    def _visible_records(self) -> List[Dict[str, Any]]:
        if not self.enabled or self.store is None:
            return []
        data = self.store.load()
        mode = self.context.get("mode")
        allowed = {"shared"}
        if mode == "wu":
            allowed.add("wu_private")
        elif mode == "chi":
            allowed.add("chi_private")
        # duo intentionally receives shared memory only, preserving private
        # knowledge boundaries even though one model renders both speakers.
        records = [
            item
            for item in data["records"]
            if isinstance(item, dict)
            and item.get("visibility") in allowed
            and item.get("status") != "superseded"
            and not _contains_secret(str(item.get("content", "")))
        ]
        return records

    @staticmethod
    def _query_terms(query: str) -> set:
        compact = re.sub(r"\s+", "", query or "")
        return {compact[index : index + 2] for index in range(max(0, len(compact) - 1))}

    def _rank_records(self, records: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        terms = self._query_terms(query)

        def score(item: Dict[str, Any]):
            content_terms = self._query_terms(str(item.get("content", "")))
            overlap = len(terms & content_terms)
            status_bonus = 50 if item.get("status") in {"pending", "planned"} else 0
            kind_bonus = 35 if item.get("kind") in {"user_fact", "preference"} else 0
            pinned_bonus = 100 if item.get("pinned") else 0
            importance = int(item.get("importance", 1)) * 5
            return (
                pinned_bonus + status_bonus + kind_bonus + overlap * 10 + importance,
                str(item.get("updated_at", "")),
            )

        return sorted(records, key=score, reverse=True)[: self.max_context_records]

    async def query_memory(self, query: str) -> str:
        if not self.enabled:
            return ""
        try:
            records = self._rank_records(self._visible_records(), query)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.bind(tag=TAG).error(f"读取持续生活记忆失败: {exc}")
            records = []
        now = self._current_time()
        lines = [
            "持续生活时间线（只在人物内部使用，不逐字朗读）：",
            f"现在是 {now.strftime('%Y-%m-%d %H:%M:%S')}，{now.tzname() or '本地时区'}。",
            "计划日期到了也不等于已经完成；没有完成记录时，只能自然确认近况。",
        ]
        if not records:
            lines.append("目前没有与这次谈话相关的长期生活记忆。")
            return "\n".join(lines)
        labels = {
            "active": "已确认",
            "pending": "人物提出、尚未接受",
            "planned": "已经约定、尚未确认完成",
            "completed": "已经发生",
            "cancelled": "已经取消",
        }
        for item in records:
            event_at = f"，时间 {item['event_at']}" if item.get("event_at") else ""
            lines.append(
                f"- [{labels.get(item.get('status'), '已记录')}] {item.get('content')}{event_at}"
            )
        return "\n".join(lines)

    @staticmethod
    def _dialogue_messages(msgs: Iterable[object]) -> List[Tuple[str, str]]:
        result: List[Tuple[str, str]] = []
        for msg in msgs:
            role = getattr(msg, "role", None)
            if role not in {"user", "assistant"} or getattr(msg, "is_temporary", False):
                continue
            content = _message_text(getattr(msg, "content", None))
            if content and not _contains_secret(content):
                result.append((role, content))
        return result

    def _catalog_for_extractor(self) -> str:
        if not self.enabled or self.store is None:
            return "[]"
        compact = []
        # Never expose the other speaker's private memory to the extractor.
        # This catalog follows the same visibility boundary as role-play reads.
        for item in self._visible_records():
            compact.append(
                {
                    key: item.get(key)
                    for key in (
                        "id",
                        "kind",
                        "visibility",
                        "status",
                        "content",
                        "event_at",
                    )
                }
            )
        return json.dumps(compact[-120:], ensure_ascii=False, separators=(",", ":"))

    def _writable_visibilities(self) -> set:
        mode = self.context.get("mode")
        if mode == "wu":
            return {"shared", "wu_private"}
        if mode == "chi":
            return {"shared", "chi_private"}
        # The duo renderer must not create or alter either man's private memory.
        return {"shared"}

    async def save_memory(self, msgs, session_id=None):
        if not self.enabled or self.llm is None or self.store is None:
            return None
        messages = self._dialogue_messages(msgs)
        if not messages:
            return None
        transcript = "\n".join(
            ("User" if role == "user" else "Assistant") + ": " + text
            for role, text in messages[-80:]
        )
        request = (
            f"当前时间：{self._current_time().isoformat(timespec='seconds')}\n"
            f"当前模式：{self.context.get('mode')}\n"
            f"现有记忆目录：{self._catalog_for_extractor()}\n"
            f"本次对话：\n{transcript}"
        )
        try:
            raw = self.llm.response_no_stream(
                EXTRACTION_PROMPT,
                request,
                max_tokens=2200,
                temperature=0.1,
            )
            decoded = _parse_json_object(raw)
            visible_target_ids = {
                item.get("id")
                for item in self._visible_records()
                if isinstance(item.get("id"), str)
            }
            applied = self.store.apply_actions(
                decoded.get("actions"),
                messages,
                session_id,
                allowed_visibilities=self._writable_visibilities(),
                allowed_target_ids=visible_target_ids,
            )
            logger.bind(tag=TAG).info(
                f"持续生活记忆保存完成: owner={self.context.get('owner_id')} applied={applied}"
            )
            return applied
        except Exception as exc:
            logger.bind(tag=TAG).error(f"持续生活记忆保存失败: {exc}")
            return None
