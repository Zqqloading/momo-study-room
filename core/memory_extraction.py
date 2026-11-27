"""单元结束后的用户记忆提炼：提示词、JSON 解析与逐条校验。

解析只认用户原话的子串；诊断/进度词直接丢弃；同批重复只留第一条。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .memory import KIND_STRENGTH, QUOTE_MAX_CHARS, TEXT_MAX_CHARS
from .scoring import ScoringError, extract_json_object

logger = logging.getLogger(__name__)

MAX_MEMORIES = 5
ALLOWED_KINDS = frozenset({"quote", "preference", "feeling"})
_DIAGNOSTIC_WORDS = (
    "性格",
    "智力",
    "能力",
    "焦虑",
    "抑郁",
    "自卑",
    "基础差",
    "不擅长",
    "心理",
    "家庭",
    "病史",
)
_PROGRESS_WORDS = ("掌握度", "分数", "mastery", "错题", "薄弱")
_PROGRESS_PATTERN = re.compile(r"第\s*\d+\s*题")
_TRAILING_PUNCT = "。！？!?；;，,、"

EXTRACTION_SYSTEM_PROMPT = """你是用户记忆提炼器。只从本轮学习单元里用户自己说过的话提炼，最多 5 条。

允许三类：
- quote 原话：用户自己说的一句有信息量的话，尽量保留原措辞。
- preference 偏好：稳定的喜好、习惯、学习方式。
- feeling 感受：当下对题目、内容或难度的情绪或体感。

每条规则：
- text 写一句提炼过的话，≤100 字，用中性、无主语的写法；
  不要写“用户是……的人”。
- source_quote 逐字引用用户原话中的一个片段，≤200 字；
  必须是用户原话的子串，不得改写。
- 只记录用户明确说过的内容；不推断性格、能力、智力、心理状态、家庭或健康。
- 不记录分数、掌握度、错题、薄弱知识点；这些留在学习进度。
- 不记录姓名、住址、联系方式等可识别身份的信息。
- 没有足够依据就返回空列表，不要凑数。

只返回 JSON：
{"memories":[{"kind":"quote|preference|feeling","text":"...","source_quote":"..."}]}"""


class MemoryParseError(ValueError):
    """提炼输出不符合 JSON 契约，调用方据此重试。"""


@dataclass(frozen=True, slots=True)
class MemoryDraft:
    kind: str
    text: str
    source_quote: str
    source_question_id: int | None = None


def normalize_text(text: str) -> str:
    cleaned = " ".join((text or "").split()).strip()
    return cleaned.rstrip(_TRAILING_PUNCT)


def _normalize_quote(text: str) -> str:
    return "".join((text or "").split())


def _has_any(text: str, words: Sequence[str]) -> bool:
    return any(word in text for word in words)


def build_extraction_messages(
    user_texts: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    lines = ["本单元用户原话（题目只作上下文，不是用户原话）：", ""]
    for item in user_texts:
        question = str(item.get("question_text") or "").strip()
        if question:
            lines.append(f"题目：{question}")
        lines.append(f"用户原话：{str(item.get('text') or '').strip()}")
        lines.append("")
    return EXTRACTION_SYSTEM_PROMPT, "\n".join(lines).strip()


def parse_memories(
    raw: str, user_texts: Sequence[Mapping[str, Any]]
) -> list[MemoryDraft]:
    """按契约解析；memories 不是列表抛 MemoryParseError，其余逐条丢弃。"""
    try:
        payload = extract_json_object(raw)
    except ScoringError as exc:
        raise MemoryParseError(str(exc)) from exc
    items = payload.get("memories")
    if not isinstance(items, list):
        raise MemoryParseError("memories 缺失或不是列表")

    quoted = [
        (_normalize_quote(str(item.get("text") or "")), item.get("question_id"))
        for item in user_texts
    ]
    drafts: list[MemoryDraft] = []
    seen: set[tuple[str, str]] = set()
    for item in items[:MAX_MEMORIES]:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "").strip()
        if kind not in ALLOWED_KINDS:
            continue
        text = str(item.get("text") or "").strip()
        if not text or len(text) > TEXT_MAX_CHARS:
            continue
        source_quote = str(item.get("source_quote") or "").strip()
        if not source_quote or len(source_quote) > QUOTE_MAX_CHARS:
            continue
        normalized_quote = _normalize_quote(source_quote)
        if not normalized_quote:
            continue
        matched = next(
            (
                (True, qid)
                for normalized_text, qid in quoted
                if normalized_quote in normalized_text
            ),
            (False, None),
        )
        if not matched[0]:
            continue
        question_id = matched[1]
        if _has_any(text, _DIAGNOSTIC_WORDS):
            logger.warning("memory_dropped_diagnostic")
            continue
        if _has_any(text, _PROGRESS_WORDS) or _PROGRESS_PATTERN.search(text):
            logger.warning("memory_dropped_progress")
            continue
        key = (kind, normalize_text(text))
        if key in seen:
            continue
        seen.add(key)
        drafts.append(
            MemoryDraft(
                kind=kind,
                text=text,
                source_quote=source_quote,
                source_question_id=question_id,
            )
        )
    return drafts


def initial_strength(kind: str) -> float:
    return KIND_STRENGTH[kind]
