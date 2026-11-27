from __future__ import annotations

import pytest

from core.concepts import Concept, Source
from core.question_generation import QUESTION_TYPES, build_session_plan


def make_concept(concept_id: str) -> Concept:
    return Concept(
        id=concept_id,
        name=concept_id.upper(),
        aliases=(),
        plain_def=f"{concept_id} 的简要定义",
        difficulty=1,
        prerequisites=(),
        source=Source(
            url=f"https://example.com/{concept_id}",
            excerpt=f"{concept_id} 的出处摘录",
        ),
    )


def test_plan_without_review_uses_five_types() -> None:
    plan = build_session_plan(
        main_concept=make_concept("mvp"), review_concept=None
    )

    assert plan.kind == "daily"
    assert plan.review_concept is None
    assert [slot.slot for slot in plan.slots] == [1, 2, 3, 4, 5]
    assert [slot.question_type for slot in plan.slots] == list(QUESTION_TYPES)
    assert all(slot.concept_id == "mvp" for slot in plan.slots)
    assert all(slot.role == "new" for slot in plan.slots)


def test_plan_with_review_splits_three_main_two_review() -> None:
    plan = build_session_plan(
        main_concept=make_concept("mvp"), review_concept=make_concept("rag")
    )

    assert plan.kind == "daily"
    assert [
        (slot.slot, slot.concept_id, slot.role, slot.question_type)
        for slot in plan.slots
    ] == [
        (1, "mvp", "new", "concept"),
        (2, "mvp", "new", "business"),
        (3, "mvp", "new", "tradeoff"),
        (4, "rag", "review", "cost_risk"),
        (5, "rag", "review", "synthesis"),
    ]


def test_plan_review_only_uses_review_kind() -> None:
    plan = build_session_plan(
        main_concept=None, review_concept=make_concept("rag")
    )

    assert plan.kind == "review"
    assert plan.main_concept is None
    assert [slot.question_type for slot in plan.slots] == list(QUESTION_TYPES)
    assert all(slot.concept_id == "rag" for slot in plan.slots)
    assert all(slot.role == "review" for slot in plan.slots)


def test_plan_same_concept_splits_two_review_three_new() -> None:
    mvp = make_concept("mvp")
    plan = build_session_plan(main_concept=mvp, review_concept=mvp)

    assert plan.kind == "daily"
    assert all(slot.concept_id == "mvp" for slot in plan.slots)
    assert [slot.role for slot in plan.slots] == [
        "new",
        "new",
        "new",
        "review",
        "review",
    ]
    assert plan.slots[3].question_type == "cost_risk"
    assert plan.slots[4].question_type == "synthesis"


def test_plan_requires_at_least_one_concept() -> None:
    with pytest.raises(ValueError):
        build_session_plan(main_concept=None, review_concept=None)
