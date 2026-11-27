"""用户长期记忆：温度、衰减、回忆、沉底与开场渲染。

只处理「关于用户」的三类记忆；不读写学习进度。纯函数便于单测；
持久化在 Store，异步提炼在 BFF。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

KIND_STRENGTH = {"quote": 1.0, "preference": 0.75, "feeling": 0.5}
HALF_LIFE_DAYS = 14.0
DORMANT_THRESHOLD = 0.05
WAKE_MIN_STRENGTH = 0.1
MAX_OPENING_ITEMS = 3
MAX_OPENING_CHARS = 300
MAX_PREAMBLE_CHARS = 360
QUOTE_RENDER_MAX = 60
TEXT_MAX_CHARS = 100
QUOTE_MAX_CHARS = 200

_OPENING_PREFIX = "先想起几件你说过的事："
_CLUE_TRIGGERS = (
    "记不记得",
    "还记得",
    "之前说过",
    "我以前说",
    "我之前说",
    "帮我回忆",
    "想想我之前",
    "我说过什么",
)
_CLUE_FILLERS = (
    "之前",
    "以前",
    "说过",
    "什么",
    "帮我",
    "回忆",
    "想想",
    "记得",
    "我",
    "你",
    "还",
    "说",
    "讲",
    "吗",
    "呢",
    "吧",
    "啊",
    "呀",
    "的",
    "是",
)
_CLUE_PUNCT = re.compile(r"[\s，。！？、；：,.!?;:…~～\"“”‘’（）()]")


@dataclass(frozen=True, slots=True)
class OpeningBlock:
    text: str
    selected: tuple[Mapping[str, Any], ...]


def _as_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _align_timezone(later: datetime, earlier: datetime) -> tuple[datetime, datetime]:
    if later.tzinfo is not None and earlier.tzinfo is None:
        later = later.replace(tzinfo=None)
    elif later.tzinfo is None and earlier.tzinfo is not None:
        earlier = earlier.replace(tzinfo=None)
    return later, earlier


def current_strength(memory: Mapping[str, Any], now: datetime) -> float:
    """strength * 0.5 ** (age_days / half_life_days)；解析失败按未衰减。"""
    strength = float(memory.get("strength") or 0.0)
    last = _as_datetime(str(memory.get("last_recalled_at") or ""))
    if last is None:
        return strength
    now, last = _align_timezone(now, last)
    age_days = max(0.0, (now - last).total_seconds() / 86400.0)
    half_life = float(memory.get("half_life_days") or HALF_LIFE_DAYS)
    if half_life <= 0:
        return strength
    return strength * 0.5 ** (age_days / half_life)


def is_dormant(memory: Mapping[str, Any], now: datetime) -> bool:
    return current_strength(memory, now) < DORMANT_THRESHOLD


def recall_update(
    memory: Mapping[str, Any],
    now: datetime,
    *,
    strong: bool = False,
    rng: Any = random.uniform,
) -> dict[str, Any]:
    """回忆保留当前强度，重抽半衰期；显式回忆把强度拉回至少 0.1。"""
    current = current_strength(memory, now)
    strength = max(current, WAKE_MIN_STRENGTH) if strong else current
    return {
        "strength": strength,
        "half_life_days": HALF_LIFE_DAYS * rng(0.5, 1.5),
        "last_recalled_at": now.isoformat(timespec="seconds"),
        "recall_count": int(memory.get("recall_count") or 0) + 1,
    }


def rank_for_opening(
    memories: Sequence[Mapping[str, Any]], now: datetime
) -> list[Mapping[str, Any]]:
    active = [
        (current_strength(memory, now), memory)
        for memory in memories
        if not is_dormant(memory, now)
    ]
    active.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("last_recalled_at") or ""),
            int(item[1].get("id") or 0),
        )
    )
    return [memory for _, memory in active]


def render_memory_line(memory: Mapping[str, Any]) -> str:
    kind = str(memory.get("kind") or "")
    text = str(memory.get("text") or "").strip()
    quote = " ".join(str(memory.get("source_quote") or "").split())
    if kind == "quote":
        if quote and len(quote) <= QUOTE_RENDER_MAX:
            return f"你说过“{quote}”"
        return f"你说过{text}"
    if kind == "preference":
        return f"你提过{text}"
    return f"你说过{text}"


def render_opening(
    memories: Sequence[Mapping[str, Any]],
    now: datetime,
    *,
    max_chars: int = MAX_OPENING_CHARS,
    max_items: int = MAX_OPENING_ITEMS,
) -> OpeningBlock:
    """按强度取最多 3 条，渲染后 ≤max_chars（含前缀和分隔符）。"""
    lines: list[str] = []
    selected: list[Mapping[str, Any]] = []
    total = len(_OPENING_PREFIX) + 1  # 句末。
    for memory in rank_for_opening(memories, now):
        if len(selected) >= max_items:
            break
        line = render_memory_line(memory)
        addition = len(line) + (1 if lines else 0)  # 「；」
        if total + addition > max_chars:
            break
        lines.append(line)
        selected.append(memory)
        total += addition
    if not lines:
        return OpeningBlock(text="", selected=())
    return OpeningBlock(
        text=f"{_OPENING_PREFIX}{'；'.join(lines)}。",
        selected=tuple(selected),
    )


def compose_preamble(
    life: str,
    memory_block: str,
    *,
    max_chars: int = MAX_PREAMBLE_CHARS,
) -> str:
    """生活句 + 记忆块；总长不超过 max_chars，记忆放不下就整块不要。"""
    life = (life or "").strip()
    if life and life[-1] not in "。！？…":
        life += "。"
    memory_block = (memory_block or "").strip()
    if memory_block and len(life) + len(memory_block) <= max_chars:
        return f"{life}{memory_block}"
    return life


def extract_clue(text: str) -> str:
    """命中回忆意图且去掉说法后还剩 ≥2 字内容线索才返回线索。"""
    raw = (text or "").strip()
    for trigger in sorted(_CLUE_TRIGGERS, key=len, reverse=True):
        if trigger not in raw:
            continue
        clue = raw.replace(trigger, " ", 1)
        for filler in sorted(_CLUE_FILLERS, key=len, reverse=True):
            clue = clue.replace(filler, " ")
        clue = _CLUE_PUNCT.sub("", clue)
        return clue if len(clue) >= 2 else ""
    return ""
