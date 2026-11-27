"""进度选题：最近失手 → 掌握度最低 → 无信号时按天稳定随机。

只读纯函数：不写库、不调模型；Coach 的 propose/start 共用。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .concepts import Concept
from .models import ConceptAssessment, ConceptState
from .planner import Planner

RECENT_MISS_MIN_SCORE = 60
RECENT_MISS_AVG_SCORE = 80


@dataclass(frozen=True, slots=True)
class TopicSelection:
    state: ConceptState
    reason_kind: str  # recent_miss | lowest_mastery | no_signal
    assessment: ConceptAssessment | None = None


def is_recent_miss(assessment: ConceptAssessment) -> bool:
    """任一题 <60 或该次均分 <80；按主题最近一次作答判断。"""
    return (
        assessment.min_score < RECENT_MISS_MIN_SCORE
        or assessment.avg_score < RECENT_MISS_AVG_SCORE
    )


def stable_pick(ids: list[str], today: str) -> str:
    """按天稳定的伪随机；同一天、同一池在任意进程结果一致。"""
    ordered = sorted(ids)
    seed = f"{today}:{','.join(ordered)}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return ordered[int(digest, 16) % len(ordered)]


def select_topic(
    states: list[ConceptState],
    assessments: dict[str, ConceptAssessment],
    concepts: list[Concept],
    today: str,
) -> TopicSelection | None:
    concepts_by_id = {concept.id: concept for concept in concepts}
    states_by_id = {state.id: state for state in states}
    active = [
        state
        for state in states
        if state.status == "active" and state.id in concepts_by_id
    ]
    if not active:
        return None

    # 1) 最近失手：最近一次有评分的作答里任一题 <60 或均分 <80
    weak = [
        (state, assessments[state.id])
        for state in active
        if state.id in assessments and is_recent_miss(assessments[state.id])
    ]
    if weak:
        weak.sort(key=lambda item: item[0].id)
        weak.sort(
            key=lambda item: (
                item[1].date,
                -item[1].avg_score,
                -item[1].min_score,
            ),
            reverse=True,
        )
        state, assessment = weak[0]
        return TopicSelection(
            state=state, reason_kind="recent_miss", assessment=assessment
        )

    # 2) 掌握度最低：学过的都可选；没学过的必须前置已满足
    planner = Planner(concepts)
    candidates = [
        state
        for state in active
        if state.last_seen is not None
        or planner.unlocked(state.id, states_by_id)
    ]
    if not candidates:
        return None

    lowest = min(state.mastery for state in candidates)
    pool = [state for state in candidates if state.mastery == lowest]

    # 3) 无信号：整池都没学过 → 稳定随机；否则久未学优先
    if all(state.last_seen is None for state in pool):
        chosen = stable_pick([state.id for state in pool], today)
        state = next(item for item in pool if item.id == chosen)
        return TopicSelection(state=state, reason_kind="no_signal")

    state = min(pool, key=lambda item: (item.last_seen or "", item.id))
    return TopicSelection(state=state, reason_kind="lowest_mastery")
