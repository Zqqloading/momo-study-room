"""MOMO 的情绪状态：两个数、衰减、边界与语气提示。

业务值只在 0.1 格上；衰减在读时计算、不写回。提示词与解析
不依赖 BFF，便于单测。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from .scoring import ScoringError, extract_json_object

COMFORT_MIN = -1.0
COMFORT_MAX = 1.0
ENERGY_MIN = 0.0
ENERGY_MAX = 1.0
COMFORT_MID = 0.0
ENERGY_MID = 0.5
HALF_LIFE_HOURS = 2.0
DELTA_LIMIT = 0.3
STEP = 0.1

COMFORT_HIGH = 0.4
COMFORT_LOW = -0.3
ENERGY_HIGH = 0.7
ENERGY_LOW = 0.4

_LEVEL_HINTS = {
    ("high", "high"): "语气轻快一点，可以带一点调侃，但只调侃话题，不调侃用户。",
    ("high", "mid"): "语气放松，正常聊，不用刻意热络。",
    ("high", "low"): "心情不差，但没什么劲；语气温和，别硬撑热情。",
    ("mid", "high"): "有精神，语气可以明快一点。",
    ("mid", "mid"): "语气平稳自然。",
    ("mid", "low"): "有点累，语气放轻，别硬撑。",
    ("low", "high"): "不太舒服但还有劲；语气直接一点，别赔笑。",
    ("low", "mid"): "不太舒服；语气收着点，不耍脾气。",
    ("low", "low"): "又累又不舒服；语气低一点，简短，别硬撑也别冷脸。",
}

UPDATE_SYSTEM_PROMPT = """你是 MOMO 的情绪状态更新器。只看用户这一轮和最近几轮聊天，
判断用户的话对 MOMO 两个数的影响。

规则：
- 只判断用户的情绪、语气、互动方式；不判断教学内容、题目难度、分数。
- 每个维度给一个 delta，常规范围 -0.3 到 0.3。
- 用户情绪波动特别大时，可以超过 0.3，但把 intense 设为 true。
- 没有明显情绪线索时，两个 delta 都给 0。
- 不要根据 assistant 的话判断 MOMO 自己的情绪；assistant 的话只作上下文。
- 只返回 JSON：
  {"comfort_delta":0.0,"energy_delta":0.0,"intense":false,"reason":"..."}"""


@dataclass(frozen=True, slots=True)
class Emotion:
    comfort: float
    energy: float


@dataclass(frozen=True, slots=True)
class EmotionUpdate:
    comfort_delta: float = 0.0
    energy_delta: float = 0.0
    intense: bool = False
    reason: str = ""


MIDPOINT = Emotion(comfort=COMFORT_MID, energy=ENERGY_MID)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def round_tenth(value: float) -> float:
    """half-up 到 0.1：-0.05 → -0.1，不用 banker's rounding。"""
    scaled = value * 10
    if scaled >= 0:
        rounded = math.floor(scaled + 0.5)
    else:
        rounded = math.ceil(scaled - 0.5)
    result = rounded / 10
    return 0.0 if result == 0 else result


def _hours_since(updated_at: str, now: datetime) -> float:
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return 0.0
    if updated.tzinfo is not None and now.tzinfo is None:
        updated = updated.replace(tzinfo=None)
    elif updated.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return max(0.0, (now - updated).total_seconds() / 3600.0)


def decay(state: Emotion, updated_at: str, now: datetime) -> Emotion:
    """每 2 小时向中间态距离减半；读时算，不写回。"""
    hours = _hours_since(updated_at, now)
    factor = 0.5 ** (hours / HALF_LIFE_HOURS)
    return Emotion(
        comfort=COMFORT_MID + (state.comfort - COMFORT_MID) * factor,
        energy=ENERGY_MID + (state.energy - ENERGY_MID) * factor,
    )


def apply_delta(base: Emotion, update: EmotionUpdate) -> Emotion:
    """常规每维最多 ±0.3；intense 跳过夹取；先加、再取整、最后夹边界。"""
    dc = update.comfort_delta
    de = update.energy_delta
    if not update.intense:
        dc = _clamp(dc, -DELTA_LIMIT, DELTA_LIMIT)
        de = _clamp(de, -DELTA_LIMIT, DELTA_LIMIT)
    comfort = _clamp(
        round_tenth(base.comfort + dc), COMFORT_MIN, COMFORT_MAX
    )
    energy = _clamp(round_tenth(base.energy + de), ENERGY_MIN, ENERGY_MAX)
    return Emotion(comfort=comfort, energy=energy)


def _comfort_level(comfort: float) -> str:
    if comfort >= COMFORT_HIGH:
        return "high"
    if comfort <= COMFORT_LOW:
        return "low"
    return "mid"


def _energy_level(energy: float) -> str:
    if energy >= ENERGY_HIGH:
        return "high"
    if energy < ENERGY_LOW:
        return "low"
    return "mid"


def tone_hint(state: Emotion) -> str:
    """3×3 分档，固定一句；不含原始数字。"""
    return _LEVEL_HINTS[(_comfort_level(state.comfort), _energy_level(state.energy))]


def build_emotion_update_messages(
    state: Emotion,
    user_text: str,
    history: Sequence[tuple[str, str]] = (),
) -> tuple[str, str]:
    recent = "\n".join(
        f"{role}: {text}" for role, text in history[-6:]
    ) or "（无）"
    user_prompt = (
        f"当前状态（已按时间衰减）：\n"
        f"- 舒不舒服：{state.comfort:.1f}（-1 到 1）\n"
        f"- 今天有没有劲：{state.energy:.1f}（0 到 1）\n\n"
        f"用户这一轮说：\n{user_text}\n\n"
        f"最近几轮（与回复同一历史窗口，最近 6 条）：\n{recent}\n\n"
        "只返回 JSON。"
    )
    return UPDATE_SYSTEM_PROMPT, user_prompt


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    number = float(value)
    return number if math.isfinite(number) else 0.0


def parse_emotion_update(raw: str) -> EmotionUpdate:
    """缺字段、非数字、非布尔、非法 JSON 一律按 0 / false 处理。"""
    try:
        payload = extract_json_object(raw)
    except ScoringError:
        return EmotionUpdate()
    reason = payload.get("reason")
    return EmotionUpdate(
        comfort_delta=_number(payload.get("comfort_delta")),
        energy_delta=_number(payload.get("energy_delta")),
        intense=payload.get("intense") is True,
        reason=reason if isinstance(reason, str) else "",
    )
