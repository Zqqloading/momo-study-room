from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace

import pytest

from core.models import SessionRecord, SessionResult
from core.store import SessionAlreadyFinalized
from support import FakeQuestionGenerator, ScriptedScorer, make_coach


def answer_all(store, coach, started, score: int = 70):
    answers = []
    for question in started.questions:
        text = "C" if question.kind == "discriminate" else "我的回答"
        answers.append(asyncio.run(coach.answer(started.session_id, question.id, text)))
    return answers


def test_complete_session_settles_and_updates_state() -> None:
    store, coach, _ = make_coach()
    try:
        started = asyncio.run(coach.start())
        answer_all(store, coach, started)

        settlement = coach.finish(started.session_id)
        assert settlement.status == "completed"
        assert settlement.session_score == 70.0
        assert settlement.mastery == {"agent-loop": 4}
        assert len(settlement.concepts) == 1
        summary = settlement.concepts[0]
        assert summary.concept_id == "agent-loop"
        assert summary.name == "Agent 循环"
        assert summary.roles == ("new",)
        assert summary.new_score == 70.0
        assert summary.review_score is None
        assert summary.mastery_before == 0
        assert summary.mastery_before_label == "未掌握"
        assert summary.mastery_after == 4
        assert summary.mastery_after_label == "熟练"
        assert summary.mastery_updated is True
        assert summary.review_due_at == "2026-11-24"

        session = store.session(started.session_id)
        assert session is not None
        assert session["status"] == "completed"
        assert session["session_score"] == 70.0

        concept = store.concept_state("agent-loop")
        assert concept is not None
        assert concept.mastery == 4
        assert concept.review_due_at == "2026-11-24"
        assert concept.review_started_at is None
        assert concept.last_seen == "2026-11-23"

        agent = store.agent_session(started.session_id)
        assert agent is not None
        assert agent["status"] == "finished"

        concepts = store.conn.execute(
            "SELECT concept_id FROM session_concepts WHERE session_id = ?",
            (started.session_id,),
        ).fetchall()
        assert [row["concept_id"] for row in concepts] == ["agent-loop"]
    finally:
        store.close()


def test_finish_early_marks_partial_and_keeps_mastery() -> None:
    store, coach, _ = make_coach()
    try:
        started = asyncio.run(coach.start())
        for question in started.questions[:2]:
            asyncio.run(coach.answer(started.session_id, question.id, "我的回答"))

        settlement = coach.finish(started.session_id)
        assert settlement.status == "partial"
        assert len(settlement.scores) == 2
        assert len(settlement.concepts) == 1
        summary = settlement.concepts[0]
        assert summary.roles == ("new",)
        assert summary.new_score == 70.0
        assert summary.mastery_before == 0
        assert summary.mastery_after == 0
        assert summary.mastery_updated is False
        assert summary.review_due_at == "2026-11-24"

        concept = store.concept_state("agent-loop")
        assert concept is not None
        assert concept.mastery == 0
    finally:
        store.close()


def test_zero_scored_marks_unscored_and_keeps_answers() -> None:
    store, coach, _ = make_coach(scorer=ScriptedScorer([ValueError("x"), ValueError("x")]))
    try:
        agent_loop = store.concept_state("agent-loop")
        tool_use = store.concept_state("tool-use")
        assert agent_loop is not None and tool_use is not None
        store.upsert_concept(replace(agent_loop, status="known"))
        store.upsert_concept(replace(tool_use, review_due_at="2026-11-23"))

        started = asyncio.run(coach.start())
        assert started.kind == "review"
        question = started.questions[0]
        asyncio.run(coach.answer(started.session_id, question.id, "我不会"))

        settlement = coach.finish(started.session_id)
        assert settlement.status == "unscored"
        assert settlement.session_score is None
        assert len(settlement.concepts) == 1
        summary = settlement.concepts[0]
        assert summary.concept_id == "tool-use"
        assert summary.roles == ("review",)
        assert summary.new_score is None
        assert summary.review_score is None
        assert summary.mastery_before == 0
        assert summary.mastery_after == 0
        assert summary.mastery_updated is False
        assert summary.review_due_at == "2026-11-23"

        row = store.question(question.id)
        assert row is not None
        assert row["answer_text"] == "我不会"
    finally:
        store.close()


def test_review_only_completed_keeps_mastery_and_reschedules() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        agent_loop = store.concept_state("agent-loop")
        memory = store.concept_state("memory")
        tool_use = store.concept_state("tool-use")
        assert agent_loop and memory and tool_use
        store.upsert_concept(replace(agent_loop, status="known"))
        store.upsert_concept(replace(memory, status="known"))
        store.upsert_concept(replace(tool_use, review_due_at="2026-11-23"))

        started = asyncio.run(coach.start())
        assert started.kind == "review"
        answer_all(store, coach, started)
        settlement = coach.finish(started.session_id)

        assert settlement.status == "completed"
        assert settlement.mastery == {}
        assert len(settlement.concepts) == 1
        summary = settlement.concepts[0]
        assert summary.concept_id == "tool-use"
        assert summary.roles == ("review",)
        assert summary.new_score is None
        assert summary.review_score == 70.0
        assert summary.mastery_before == 0
        assert summary.mastery_after == 0
        assert summary.mastery_updated is False
        assert summary.review_due_at == "2026-11-24"
    finally:
        store.close()


def test_same_concept_summary_has_both_roles() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        agent_loop = store.concept_state("agent-loop")
        assert agent_loop is not None
        store.upsert_concept(replace(agent_loop, review_due_at="2026-11-23"))

        started = asyncio.run(coach.start())
        answer_all(store, coach, started)
        settlement = coach.finish(started.session_id)

        assert settlement.status == "completed"
        assert settlement.mastery == {"agent-loop": 4}
        assert len(settlement.concepts) == 1
        summary = settlement.concepts[0]
        assert summary.roles == ("new", "review")
        assert summary.new_score == 70.0
        assert summary.review_score == 70.0
        assert summary.mastery_before == 0
        assert summary.mastery_after == 4
        assert summary.mastery_updated is True
        assert summary.review_due_at == "2026-11-24"
    finally:
        store.close()


def test_finish_is_not_repeatable() -> None:
    store, coach, _ = make_coach()
    try:
        started = asyncio.run(coach.start())
        answer_all(store, coach, started)
        coach.finish(started.session_id)
        try:
            coach.finish(started.session_id)
        except SessionAlreadyFinalized:
            pass
        else:
            raise AssertionError("重复结算应被拒绝")
    finally:
        store.close()


def test_settlement_rollback_keeps_agent_session_active() -> None:
    store, coach, _ = make_coach()
    try:
        started = asyncio.run(coach.start())
        record = SessionRecord(
            session_id=started.session_id,
            date="2026-11-23",
            kind="daily",
            status="completed",
            started_at="2026-11-23T20:00:00",
            created_at="2026-11-23T20:10:00",
            concept_id="agent-loop",
            input_mode="text",
            session_score=70.0,
        )
        result = SessionResult(
            session_id=started.session_id,
            status="completed",
            session_score=70.0,
            mastery_updates={"agent-loop": 99},  # CHECK 会失败
        )
        with pytest.raises(sqlite3.IntegrityError):
            store.finalize(
                record,
                result,
                agent_session_id=started.session_id,
                finished_at="2026-11-23T20:10:00",
            )

        assert store.session(started.session_id) is None
        agent = store.agent_session(started.session_id)
        assert agent is not None
        assert agent["status"] == "active"
    finally:
        store.close()
