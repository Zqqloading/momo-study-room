from __future__ import annotations

import asyncio
from dataclasses import replace

from support import FakeQuestionGenerator, ScriptedScorer, make_coach


def review_only_env(score: int):
    scorer = ScriptedScorer(score=score)
    store, coach, _ = make_coach(
        scorer=scorer, generator=FakeQuestionGenerator()
    )
    agent_loop = store.concept_state("agent-loop")
    tool_use = store.concept_state("tool-use")
    assert agent_loop is not None and tool_use is not None
    store.upsert_concept(replace(agent_loop, status="known"))
    store.upsert_concept(replace(tool_use, review_due_at="2026-11-23"))
    return store, coach


def answer_all(coach, started) -> None:
    for question in started.questions:
        asyncio.run(
            coach.answer(started.session_id, question.id, "我的回答")
        )


def test_review_below_threshold_keeps_next_day() -> None:
    store, coach = review_only_env(score=60)
    try:
        started = asyncio.run(coach.start())
        assert started.kind == "review"
        answer_all(coach, started)

        settlement = coach.finish(started.session_id)
        assert settlement.status == "completed"

        concept = store.concept_state("tool-use")
        assert concept is not None
        assert concept.review_due_at == "2026-11-24"
        assert concept.review_started_at == "2026-11-23"
    finally:
        store.close()


def test_review_at_threshold_clears_due() -> None:
    store, coach = review_only_env(score=80)
    try:
        started = asyncio.run(coach.start())
        answer_all(coach, started)
        coach.finish(started.session_id)

        concept = store.concept_state("tool-use")
        assert concept is not None
        assert concept.review_due_at is None
        assert concept.review_started_at is None
    finally:
        store.close()


def test_due_reviews_exclude_inactive_concepts() -> None:
    store, coach, _ = make_coach()
    try:
        tool_use = store.concept_state("tool-use")
        assert tool_use is not None
        store.upsert_concept(
            replace(tool_use, status="skipped", review_due_at="2026-11-23")
        )
        assert store.due_reviews("2026-11-23") == []
    finally:
        store.close()
