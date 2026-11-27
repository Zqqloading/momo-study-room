from __future__ import annotations

import asyncio
from dataclasses import replace

from support import FakeQuestionGenerator, make_coach

def _mark_due(store, concept_id: str, due: str = "2026-11-23") -> None:
    state = store.concept_state(concept_id)
    assert state is not None
    store.upsert_concept(replace(state, review_due_at=due))


def _add_prior_daily(store, concept_id: str, score: int, day: str = "2026-11-20") -> None:
    session_id = f"prior-{concept_id}-{score}"
    store.conn.execute(
        """
        INSERT INTO sessions
          (id, date, concept_id, kind, status, started_at, input_mode, created_at)
        VALUES (?, ?, ?, 'daily', 'completed', ?, 'text', ?)
        """,
        (session_id, day, concept_id, f"{day}T20:00:00", f"{day}T20:20:00"),
    )
    store.conn.commit()
    question_id = store.add_question(
        session_id=session_id,
        question_bank_id=None,
        concept_id=concept_id,
        role="new",
        kind="apply",
        text="上一场的题",
        rubric_json={},
        source_url="fixture://prev",
        source_excerpt="上一场的出处",
        created_at=f"{day}T20:05:00",
    )
    store.save_answer(question_id, text="上一场的回答", score=score, feedback="稳定")


def _table_counts(store) -> tuple[int, int, int]:
    sessions = store.conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
    agents = store.conn.execute("SELECT COUNT(*) AS n FROM agent_sessions").fetchone()["n"]
    concepts = store.conn.execute("SELECT COUNT(*) AS n FROM concepts").fetchone()["n"]
    return (int(sessions), int(agents), int(concepts))


def test_proposal_matches_actual_start_without_review() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        proposal = coach.propose()
        assert proposal.available is True
        assert proposal.kind == "daily"
        assert proposal.main is not None
        assert proposal.main.id == "agent-loop"
        assert proposal.review is None
        assert proposal.same_concept is False
        assert proposal.question_count == 5
        assert [slot.question_type for slot in proposal.slots] == [
            "concept",
            "business",
            "tradeoff",
            "cost_risk",
            "synthesis",
        ]

        started = asyncio.run(coach.start())
        agent = store.agent_session(started.session_id)
        assert agent is not None
        assert agent["concept_id"] == proposal.main.id
        assert [(q.role, q.question_type) for q in started.questions] == [
            (slot.role, slot.question_type) for slot in proposal.slots
        ]
    finally:
        store.close()


def test_proposal_with_due_review_splits_three_and_two() -> None:
    store, coach, _ = make_coach()
    try:
        _mark_due(store, "tool-use")
        proposal = coach.propose()
        assert proposal.available is True
        assert proposal.kind == "daily"
        assert proposal.main is not None and proposal.main.id == "agent-loop"
        assert proposal.review is not None and proposal.review.id == "tool-use"
        assert proposal.same_concept is False
        assert proposal.deferred_reviews == 0
        assert [slot.concept_id for slot in proposal.slots[:3]] == ["agent-loop"] * 3
        assert [slot.concept_id for slot in proposal.slots[3:]] == ["tool-use"] * 2
        assert [slot.role for slot in proposal.slots] == [
            "new",
            "new",
            "new",
            "review",
            "review",
        ]
        assert "今天到期" in proposal.review.reason
    finally:
        store.close()


def test_proposal_review_only_when_no_new_concept() -> None:
    store, coach, _ = make_coach()
    try:
        agent_loop = store.concept_state("agent-loop")
        memory = store.concept_state("memory")
        assert agent_loop is not None and memory is not None
        store.upsert_concept(replace(agent_loop, status="known"))
        store.upsert_concept(replace(memory, status="known"))
        _mark_due(store, "tool-use")

        proposal = coach.propose()
        assert proposal.available is True
        assert proposal.kind == "review"
        assert proposal.main is None
        assert proposal.review is not None and proposal.review.id == "tool-use"
        assert proposal.question_count == 5
        assert {slot.role for slot in proposal.slots} == {"review"}
    finally:
        store.close()


def test_proposal_same_concept_marks_three_new_two_review() -> None:
    store, coach, _ = make_coach()
    try:
        _mark_due(store, "agent-loop")
        proposal = coach.propose()
        assert proposal.available is True
        assert proposal.main is not None and proposal.main.id == "agent-loop"
        assert proposal.review is not None and proposal.review.id == "agent-loop"
        assert proposal.same_concept is True
        assert [slot.role for slot in proposal.slots] == [
            "new",
            "new",
            "new",
            "review",
            "review",
        ]
    finally:
        store.close()


def test_proposal_unavailable_without_active_concepts() -> None:
    store, coach, _ = make_coach()
    try:
        for state in store.concept_states():
            store.upsert_concept(replace(state, status="known"))
        proposal = coach.propose()
        assert proposal.available is False
        assert proposal.main is None and proposal.review is None
        assert proposal.slots == ()
        assert proposal.question_count == 0
        assert "没有在学概念" in (proposal.reason or "")
    finally:
        store.close()


def test_proposal_unavailable_when_all_locked() -> None:
    store, coach, _ = make_coach()
    try:
        agent_loop = store.concept_state("agent-loop")
        assert agent_loop is not None
        store.upsert_concept(replace(agent_loop, status="known"))
        proposal = coach.propose()
        assert proposal.available is False
        assert "没有可解锁的新概念" in (proposal.reason or "")
    finally:
        store.close()


def test_proposal_is_read_only_and_deterministic() -> None:
    store, coach, _ = make_coach()
    try:
        before_counts = _table_counts(store)
        before_states = store.concept_states()
        first = coach.propose()
        second = coach.propose()
        assert first == second
        assert _table_counts(store) == before_counts
        assert store.concept_states() == before_states
    finally:
        store.close()


def test_proposal_reasons_include_prerequisite_and_last_score() -> None:
    store, coach, _ = make_coach()
    try:
        agent_loop = store.concept_state("agent-loop")
        memory = store.concept_state("memory")
        assert agent_loop is not None and memory is not None
        store.upsert_concept(replace(agent_loop, status="skipped"))
        store.upsert_concept(replace(memory, status="known"))
        _add_prior_daily(store, "tool-use", 60)
        _mark_due(store, "tool-use")

        proposal = coach.propose()
        assert proposal.available is True
        assert proposal.main is not None and proposal.main.id == "tool-use"
        assert proposal.main.prerequisites
        assert proposal.main.prerequisites[0].id == "agent-loop"
        assert proposal.main.prerequisites[0].satisfied is True
        assert "已跳过" in proposal.main.reason
        assert proposal.review is not None and proposal.review.id == "tool-use"
        assert proposal.review.last_score == 60
        assert "上次得分 60" in proposal.review.reason
        assert "低于 80" in proposal.review.reason
    finally:
        store.close()


def test_reason_kind_no_signal_and_intro() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        proposal = coach.propose()
        assert proposal.main is not None
        assert proposal.main.reason_kind == "no_signal"
        assert "从未学过" in proposal.main.reason

        started = asyncio.run(coach.start())
        assert started.focus is not None
        assert started.focus.reason_kind == "no_signal"
        assert started.intro == "今天从「Agent 循环」开始。"
    finally:
        store.close()


def test_reason_kind_lowest_mastery_and_intro() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        agent_loop = store.concept_state("agent-loop")
        assert agent_loop is not None
        store.upsert_concept(
            replace(agent_loop, mastery=2, last_seen="2026-11-20")
        )

        proposal = coach.propose()
        assert proposal.main is not None and proposal.main.id == "agent-loop"
        assert proposal.main.reason_kind == "lowest_mastery"
        assert "掌握度最低" in proposal.main.reason

        started = asyncio.run(coach.start())
        assert started.focus is not None
        assert started.focus.reason_kind == "lowest_mastery"
        assert started.intro.startswith("现在掌握度最低的是「Agent 循环」")
    finally:
        store.close()


def test_reason_kind_recent_miss_same_day_and_intro() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        agent_loop = store.concept_state("agent-loop")
        memory = store.concept_state("memory")
        assert agent_loop is not None and memory is not None
        store.upsert_concept(
            replace(
                agent_loop,
                mastery=5,
                last_seen="2026-11-20",
                review_due_at="2026-11-24",
            )
        )
        store.upsert_concept(replace(memory, mastery=0, last_seen="2026-11-20"))
        _add_prior_daily(store, "agent-loop", 40, day="2026-11-23")

        proposal = coach.propose()
        assert proposal.available is True
        assert proposal.main is not None and proposal.main.id == "agent-loop"
        assert proposal.main.reason_kind == "recent_miss"
        assert "40" in proposal.main.reason
        assert proposal.review is None

        started = asyncio.run(coach.start())
        assert started.focus is not None
        assert started.focus.reason_kind == "recent_miss"
        assert "Agent 循环" in started.intro
        assert "上次" in started.intro
    finally:
        store.close()


def test_review_only_intro() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        for concept_id in ("agent-loop", "memory"):
            state = store.concept_state(concept_id)
            assert state is not None
            store.upsert_concept(replace(state, status="known"))
        _mark_due(store, "tool-use")

        started = asyncio.run(coach.start())
        assert started.kind == "review"
        assert started.focus is not None
        assert started.focus.concept_id == "tool-use"
        assert started.focus.reason_kind == "review"
        assert started.intro == "今天先复习「工具调用」。"
    finally:
        store.close()
