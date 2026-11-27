from __future__ import annotations

import asyncio
from dataclasses import replace

from core.question_generation import QUESTION_TYPES
from support import FakeQuestionGenerator, make_coach

TODAY = "2026-11-23"


def mark_due(store, concept_id: str, due: str = TODAY) -> None:
    state = store.concept_state(concept_id)
    assert state is not None
    store.upsert_concept(replace(state, review_due_at=due))


def rows_of(store, started) -> list[dict]:
    return store.session_questions(started.session_id)


def test_start_without_reviews_uses_five_types_on_main_concept() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        started = asyncio.run(coach.start())

        assert started.kind == "daily"
        assert [q.question_type for q in started.questions] == list(QUESTION_TYPES)
        assert [q.role for q in started.questions] == ["new"] * 5
        rows = rows_of(store, started)
        assert [row["concept_id"] for row in rows] == ["agent-loop"] * 5
        assert [q.index for q in started.questions] == [1, 2, 3, 4, 5]
        assert all(q.total == 5 for q in started.questions)
        session = store.agent_session(started.session_id)
        assert session is not None
        assert session["status"] == "active"
        assert session["kind"] == "daily"
    finally:
        store.close()


def test_start_with_one_due_review_splits_three_main_two_review() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        mark_due(store, "tool-use")
        started = asyncio.run(coach.start())

        rows = rows_of(store, started)
        assert [
            (row["question_role"], row["concept_id"], row["question_type"])
            for row in rows
        ] == [
            ("new", "agent-loop", "concept"),
            ("new", "agent-loop", "business"),
            ("new", "agent-loop", "tradeoff"),
            ("review", "tool-use", "cost_risk"),
            ("review", "tool-use", "synthesis"),
        ]
    finally:
        store.close()


def test_two_due_reviews_only_take_most_overdue_concept() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        mark_due(store, "agent-loop", "2026-11-23")
        mark_due(store, "tool-use", "2026-11-22")

        started = asyncio.run(coach.start())

        rows = rows_of(store, started)
        review_rows = [
            row for row in rows if row["question_role"] == "review"
        ]
        assert len(review_rows) == 2
        assert {row["concept_id"] for row in review_rows} == {"tool-use"}
        assert len(rows) == 5
    finally:
        store.close()


def test_review_only_session_uses_five_review_questions() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        agent_loop = store.concept_state("agent-loop")
        assert agent_loop is not None
        store.upsert_concept(replace(agent_loop, status="known", mastery=0))
        mark_due(store, "tool-use")

        started = asyncio.run(coach.start())

        assert started.kind == "review"
        assert len(started.questions) == 5
        assert all(q.role == "review" for q in started.questions)
        assert [q.question_type for q in started.questions] == list(QUESTION_TYPES)
        rows = rows_of(store, started)
        assert {row["concept_id"] for row in rows} == {"tool-use"}
        session = store.agent_session(started.session_id)
        assert session is not None
        assert session["kind"] == "review"
    finally:
        store.close()


def test_same_concept_splits_two_review_three_new() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        mark_due(store, "agent-loop")

        started = asyncio.run(coach.start())

        rows = rows_of(store, started)
        assert {row["concept_id"] for row in rows} == {"agent-loop"}
        assert [row["question_role"] for row in rows] == [
            "new",
            "new",
            "new",
            "review",
            "review",
        ]
        assert [row["question_type"] for row in rows] == list(QUESTION_TYPES)
    finally:
        store.close()
