"""Runtime guardrails for the Nixi spoken role-play pack.

The prompt is the primary control.  This module is the final TTS boundary: source
and evidence jargon must never be spoken in character, even when a provider
ignores part of the prompt.  The streaming guard retains a short suffix so a
blocked phrase split across provider chunks cannot leak to audio.
"""

from __future__ import annotations

import re
from typing import Iterable, Tuple


NIXI_PROMPT_MARKER = "你正在运行《逆袭》语音角色包"

# Longest and most specific phrases go first.  Replacements deliberately sound
# like ordinary uncertain recollection, not like a database or source audit.
FORBIDDEN_ROLEPLAY_REPLACEMENTS: Tuple[Tuple[str, str], ...] = (
    ("原作没有确认的事情", "我没确认有这回事"),
    ("原作没有记载", "我没有这段记忆"),
    ("原著没有记载", "我没有这段记忆"),
    ("原文没有记载", "我没有这段记忆"),
    ("原作里没有", "我不记得有这回事"),
    ("原著里没有", "我不记得有这回事"),
    ("原文里没有", "我不记得有这回事"),
    ("剧情里没有", "我不记得有这回事"),
    ("原作没写", "这事我不记得"),
    ("原著没写", "这事我不记得"),
    ("原文没写", "这事我不记得"),
    ("剧情没写", "这事我不记得"),
    ("原作事实", "过去的事"),
    ("原著出处", "来历"),
    ("资料里没有", "我不记得有这回事"),
    ("设定中没有", "我不记得有这回事"),
    ("设定里没有", "我不记得有这回事"),
    ("小说里没有", "我不记得有这回事"),
    ("书里没有", "我不记得有这回事"),
    ("人物档案里没有", "我不记得有这回事"),
    ("知识库里没有", "我不记得有这回事"),
    ("数据库里没有", "我不记得有这回事"),
    ("根据小说原著", "照我记得的"),
    ("根据小说", "照我记得的"),
    ("根据原著", "照我记得的"),
    ("根据原作", "照我记得的"),
    ("根据原文", "照我记得的"),
    ("根据剧情", "照我记得的"),
    ("证据不足", "这事我现在说不准"),
    ("不足以判断", "这事我现在说不准"),
    ("无法从原作判断", "这事我现在说不准"),
    ("无法从原文判断", "这事我现在说不准"),
    ("信息不足", "这事我现在说不准"),
    ("缺少信息", "这事我现在说不准"),
    ("作为一个AI", "我"),
    ("作为AI", "我"),
    ("作为人工智能", "我"),
    ("作为语言模型", "我"),
    ("系统提示", "提醒"),
    ("提示词", "说法"),
    ("证据库", "过去的记录"),
    ("session fiction", "后来发生的生活"),
    ("canon", "人物底色"),
)

FORBIDDEN_ROLEPLAY_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = (
    (
        re.compile(
            r"(?:原作|原著|原文|剧情|设定|资料|小说|书|大纲|人物档案|知识库|数据库)(?:中|里)?"
            r"(?:并未|没有|没)(?:写|提及|交代|记载|确认|说明)"
        ),
        "我不记得有这回事",
    ),
    (
        re.compile(r"(?:根据|按照)(?:这部)?(?:小说|原著|原作|原文|剧情|设定|资料|大纲|人物档案|知识库|数据库)"),
        "照我记得的",
    ),
    (re.compile(r"(?:现有)?(?:证据|资料)(?:不够|不足)"), "这事我现在说不准"),
    (re.compile(r"(?:原作|原著|原文|剧情|设定|资料|小说|书|大纲)(?:中|里)?不在"), "我不记得有这回事"),
    (re.compile(r"(?:作为|身为)(?:一个)?(?:AI|人工智能|语言模型|虚构人物)"), "我"),
    (
        re.compile(
            r"(?:无法|不能)(?:单纯)?(?:从(?:原作|原著|原文|剧情|设定|资料))?判断"
        ),
        "这事我现在说不准",
    ),
)


def is_nixi_roleplay_prompt(prompt: object) -> bool:
    return isinstance(prompt, str) and NIXI_PROMPT_MARKER in prompt


def sanitize_nixi_roleplay_output(text: object) -> str:
    """Return spoken text with all backstage source jargon removed."""

    if not isinstance(text, str):
        return ""
    sanitized = text
    for forbidden, replacement in FORBIDDEN_ROLEPLAY_REPLACEMENTS:
        sanitized = sanitized.replace(forbidden, replacement)
    for pattern, replacement in FORBIDDEN_ROLEPLAY_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def forbidden_roleplay_phrases() -> Iterable[str]:
    return (item[0] for item in FORBIDDEN_ROLEPLAY_REPLACEMENTS)


class NixiStreamingOutputGuard:
    """Buffer Nixi output until it can be sanitized as one complete response.

    Regex and exact rules intentionally overlap.  Sanitizing partial chunks can
    consume the prefix of a longer phrase and expose its remaining source word.
    Nixi therefore trades first-audio latency for a strict no-backstage-speech
    guarantee.  Non-Nixi responses still pass through without buffering.
    """

    def __init__(self, enabled: bool):
        self.enabled = bool(enabled)
        self._pending = ""

    def feed(self, chunk: object) -> str:
        if not isinstance(chunk, str) or not chunk:
            return ""
        if not self.enabled:
            return chunk
        self._pending += chunk
        return ""

    def flush(self) -> str:
        if not self.enabled:
            return ""
        emitted = sanitize_nixi_roleplay_output(self._pending)
        self._pending = ""
        return emitted
