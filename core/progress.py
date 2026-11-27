"""掌握程度读模型：把 concepts 运行时状态与最近会话压成面板可直接展示的结构。

只读、纯函数；不写库、不调外部服务。标签只用于展示，不参与 mastery 计算。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping

from .concepts import Concept
from .models import ConceptAssessment, ConceptState, mastery_label
from .selection import is_recent_miss


@dataclass(frozen=True, slots=True)
class ConceptProgress:
    id: str
    name: str
    plain_def: str
    mastery: int
    mastery_label: str
    status: str
    last_seen: str | None
    review_due_at: str | None
    overdue_days: int


@dataclass(frozen=True, slots=True)
class DistributionItem:
    mastery: int
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class ProgressStats:
    active: int
    known: int
    skipped: int
    proposed: int
    orphaned: int
    avg_mastery: float | None
    distribution: tuple[DistributionItem, ...]
    due: int
    overdue: int
    weak: int


@dataclass(frozen=True, slots=True)
class UnitHistoryItem:
    session_id: str
    date: str
    kind: str
    status: str
    session_score: float | None
    concept_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProgressOverview:
    date: str
    stats: ProgressStats
    concepts: tuple[ConceptProgress, ...]
    recent_units: tuple[UnitHistoryItem, ...]


def _overdue_days(due_at: str | None, today: str) -> int:
    if not due_at:
        return 0
    try:
        return max(0, (date.fromisoformat(today) - date.fromisoformat(due_at)).days)
    except ValueError:
        return 0


def _concept_names(
    concept_ids: Iterable[str], concepts_by_id: dict[str, Concept]
) -> tuple[str, ...]:
    names: list[str] = []
    for concept_id in concept_ids:
        concept = concepts_by_id.get(concept_id)
        names.append(concept.name if concept is not None else concept_id)
    return tuple(names)


def build_overview(
    concepts: list[Concept],
    states: list[ConceptState],
    recent_units: list[dict[str, Any]],
    today: str,
    assessments: Mapping[str, ConceptAssessment] | None = None,
) -> ProgressOverview:
    concepts_by_id = {concept.id: concept for concept in concepts}
    status_counts = Counter(state.status for state in states)
    active = sorted(
        (state for state in states if state.status == "active"),
        key=lambda state: (
            state.mastery,
            state.review_due_at or "9999-12-31",
            concepts_by_id[state.id].name if state.id in concepts_by_id else state.id,
        ),
    )

    def weak(state: ConceptState) -> bool:
        assessment = (assessments or {}).get(state.id)
        if assessment is not None and is_recent_miss(assessment):
            return True
        return state.last_seen is not None and state.mastery <= 1

    rows: list[ConceptProgress] = []
    for state in active:
        concept = concepts_by_id.get(state.id)
        rows.append(
            ConceptProgress(
                id=state.id,
                name=concept.name if concept is not None else state.id,
                plain_def=concept.plain_def if concept is not None else "",
                mastery=state.mastery,
                mastery_label=mastery_label(state.mastery),
                status=state.status,
                last_seen=state.last_seen,
                review_due_at=state.review_due_at,
                overdue_days=_overdue_days(state.review_due_at, today),
            )
        )

    distribution = tuple(
        DistributionItem(
            mastery=value,
            label=mastery_label(value),
            count=sum(1 for state in active if state.mastery == value),
        )
        for value in range(6)
    )
    average = (
        round(sum(state.mastery for state in active) / len(active), 1)
        if active
        else None
    )
    stats = ProgressStats(
        active=status_counts.get("active", 0),
        known=status_counts.get("known", 0),
        skipped=status_counts.get("skipped", 0),
        proposed=status_counts.get("proposed", 0),
        orphaned=status_counts.get("orphaned", 0),
        avg_mastery=average,
        distribution=distribution,
        due=sum(
            1
            for state in active
            if state.review_due_at is not None and state.review_due_at <= today
        ),
        overdue=sum(
            1
            for state in active
            if state.review_due_at is not None and state.review_due_at < today
        ),
        weak=sum(1 for state in active if weak(state)),
    )

    history: list[UnitHistoryItem] = []
    for row in recent_units:
        raw = row.get("concept_ids") or ()
        concept_ids = (
            tuple(part for part in str(raw).split(",") if part)
            if isinstance(raw, str)
            else tuple(raw)
        )
        history.append(
            UnitHistoryItem(
                session_id=str(row.get("session_id") or ""),
                date=str(row.get("date") or ""),
                kind=str(row.get("kind") or ""),
                status=str(row.get("status") or ""),
                session_score=row.get("session_score"),
                concept_names=_concept_names(concept_ids, concepts_by_id),
            )
        )

    return ProgressOverview(
        date=today,
        stats=stats,
        concepts=tuple(rows),
        recent_units=tuple(history),
    )
