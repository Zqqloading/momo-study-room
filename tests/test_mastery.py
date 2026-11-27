from __future__ import annotations

import asyncio
from dataclasses import replace

from core.models import SessionRecord, SessionResult
from support import FakeQuestionGenerator, make_coach


def seed_daily(
    store, session_id: str, date: str, score: int, *, status: str = "completed"
) -> None:
    question_id = store.add_question(
        session_id=session_id,
        question_bank_id=None,
        concept_id="agent-loop",
        role="new",
        kind="recall",
        text="旧会话题",
        rubric_json={},
        source_url="https://example.com/agent",
        source_excerpt="旧会话摘录",
        created_at=f"{date}T20:00:00",
    )
    store.save_answer(question_id, text="旧答案", score=score, feedback="")
    store.finalize(
        SessionRecord(
            session_id=session_id,
            date=date,
            kind="daily",
            status=status,
            started_at=f"{date}T19:40:00",
            created_at=f"{date}T20:00:00",
            concept_id="agent-loop",
            input_mode="text",
            session_score=float(score),
        ),
        SessionResult(
            session_id=session_id,
            status=status,
            session_score=float(score),
        ),
    )


def answer_all(coach, started) -> None:
    for question in started.questions:
        text = "C" if question.kind == "discriminate" else "我的回答"
        asyncio.run(coach.answer(started.session_id, question.id, text))


def test_mastery_uses_latest_three_completed_daily_scores() -> None:
    store, coach, _ = make_coach()
    try:
        seed_daily(store, "d1", "2026-11-20", 40)
        seed_daily(store, "d2", "2026-11-21", 60)
        seed_daily(store, "d3", "2026-11-22", 80)

        started = asyncio.run(coach.start())
        answer_all(coach, started)
        settlement = coach.finish(started.session_id)

        # (70 + 80 + 60) / 3 = 70 -> mastery 4；若错取四次会得到 62.5 -> 3。
        assert settlement.mastery == {"agent-loop": 4}
    finally:
        store.close()


def test_partial_daily_does_not_count_toward_mastery() -> None:
    store, coach, _ = make_coach()
    try:
        seed_daily(store, "p1", "2026-11-22", 0, status="partial")

        started = asyncio.run(coach.start())
        answer_all(coach, started)
        settlement = coach.finish(started.session_id)

        # 只有当前 70 分：70 / 20 = 3.5 -> 4；若 partial 也计入会变成 2。
        assert settlement.mastery == {"agent-loop": 4}
    finally:
        store.close()


def mark_due(store, concept_id: str) -> None:
    state = store.concept_state(concept_id)
    assert state is not None
    store.upsert_concept(replace(state, review_due_at="2026-11-23"))


def test_mixed_session_updates_mastery_and_review_due() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        mark_due(store, "tool-use")

        started = asyncio.run(coach.start())
        assert [q.role for q in started.questions] == [
            "new",
            "new",
            "new",
            "review",
            "review",
        ]
        answer_all(coach, started)
        settlement = coach.finish(started.session_id)

        assert settlement.mastery == {"agent-loop": 4}
        tool_use = store.concept_state("tool-use")
        assert tool_use is not None
        assert tool_use.review_due_at == "2026-11-24"
    finally:
        store.close()


def test_same_concept_session_counts_new_scores_for_mastery() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        mark_due(store, "agent-loop")

        started = asyncio.run(coach.start())
        answer_all(coach, started)
        settlement = coach.finish(started.session_id)

        assert settlement.mastery == {"agent-loop": 4}
        agent_loop = store.concept_state("agent-loop")
        assert agent_loop is not None
        assert agent_loop.review_due_at == "2026-11-24"
    finally:
        store.close()
