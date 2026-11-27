from __future__ import annotations

import asyncio

from core.db import connect, init_schema
from core.store import Store
from support import ScriptedLLM, make_agent, make_coach


def make_store() -> Store:
    conn = connect(":memory:")
    init_schema(conn)
    return Store(conn)


def start(store: Store, session_id: str = "s1", date: str = "2026-11-23") -> None:
    store.start_agent_session(
        session_id=session_id,
        kind="daily",
        date=date,
        started_at=f"{date}T19:40:00",
    )


def add_question(store: Store, session_id: str = "s1", index: int = 0) -> int:
    return store.add_question(
        session_id=session_id,
        question_bank_id=f"agent-recall-{index}",
        concept_id="agent",
        role="new",
        kind="recall",
        text=f"问题 {index}",
        rubric_json={"levels": [0, 40, 70, 90, 100]},
        source_url="https://example.com/agent",
        source_excerpt="Agent 是能感知环境并自主采取行动的系统。",
        created_at="2026-11-23T19:41:00",
    )


def test_start_creates_active_session() -> None:
    store = make_store()
    try:
        start(store)
        row = store.agent_session("s1")
        assert row is not None
        assert row["status"] == "active"
        assert row["kind"] == "daily"
        assert row["date"] == "2026-11-23"
        assert row["input_mode"] == "text"
    finally:
        store.close()


def test_touch_updates_last_question_and_mode() -> None:
    store = make_store()
    try:
        start(store)
        question_id = add_question(store)
        store.touch_agent_session(
            "s1",
            last_question_id=question_id,
            input_mode="voice",
            updated_at="2026-11-23T19:45:00",
        )
        row = store.agent_session("s1")
        assert row is not None
        assert row["last_question_id"] == question_id
        assert row["input_mode"] == "voice"
        assert row["updated_at"] == "2026-11-23T19:45:00"
    finally:
        store.close()


def test_abandon_only_abandons_previous_days() -> None:
    store = make_store()
    try:
        start(store, "old", "2026-11-22")
        start(store, "today", "2026-11-23")
        count = store.abandon_stale_agent_sessions(
            today="2026-11-23", updated_at="2026-11-23T19:40:00"
        )
        assert count == 1
        old = store.agent_session("old")
        today = store.agent_session("today")
        assert old is not None and old["status"] == "abandoned"
        assert today is not None and today["status"] == "active"
    finally:
        store.close()


def test_first_unanswered_skips_answered_questions() -> None:
    store = make_store()
    try:
        start(store)
        first = add_question(store, index=0)
        second = add_question(store, index=1)
        store.save_answer(first, text="不知道", score=0, feedback="短定义")
        question = store.first_unanswered_question("s1")
        assert question is not None
        assert question["id"] == second
    finally:
        store.close()


def test_first_unanswered_returns_none_when_all_answered() -> None:
    store = make_store()
    try:
        start(store)
        question_id = add_question(store)
        store.save_answer(question_id, text="答案", score=70, feedback="好")
        assert store.first_unanswered_question("s1") is None
    finally:
        store.close()


def test_session_notes_roundtrip() -> None:
    store = make_store()
    try:
        start(store)
        question_id = add_question(store)
        note_id = store.add_session_note(
            session_id="s1",
            question_id=question_id,
            mode="probe",
            input_text="知道了",
            output_text="能举个例子吗？",
            created_at="2026-11-23T19:50:00",
        )
        notes = store.session_notes("s1")
        assert len(notes) == 1
        assert notes[0]["id"] == note_id
        assert notes[0]["mode"] == "probe"
        assert notes[0]["question_id"] == question_id
    finally:
        store.close()


def answer_text(question) -> str:
    return "C" if question.kind == "discriminate" else "我的回答"


# ---- Agent 会话生命周期 ----


def test_agent_start_abandons_stale_sessions() -> None:
    store, _, _ = make_coach()
    try:
        store.start_agent_session(
            session_id="old",
            kind="daily",
            date="2026-11-22",
            started_at="2026-11-22T19:40:00",
        )
        agent, _ = make_agent(store)
        started = asyncio.run(agent.start())
        old = store.agent_session("old")
        assert old is not None
        assert old["status"] == "abandoned"
        assert store.agent_session(started.session_id)["status"] == "active"  # type: ignore[index]
    finally:
        store.close()


def test_agent_submit_scores_and_returns_next_question() -> None:
    store, _, _ = make_coach()
    try:
        agent, _ = make_agent(store)
        started = asyncio.run(agent.start())
        first, second = started.questions[0], started.questions[1]

        turn = asyncio.run(agent.submit(started.session_id, first.id, answer_text(first)))
        assert turn.kind == "scored"
        assert turn.answer is not None
        assert turn.next_question is not None
        assert turn.next_question["id"] == second.id
    finally:
        store.close()


def test_agent_submit_settles_after_last_question() -> None:
    store, _, _ = make_coach()
    try:
        agent, _ = make_agent(store)
        started = asyncio.run(agent.start())
        last = None
        for question in started.questions:
            last = asyncio.run(
                agent.submit(started.session_id, question.id, answer_text(question))
            )
        assert last is not None
        assert last.kind == "settled"
        assert last.settlement is not None
        assert last.settlement.status == "completed"
    finally:
        store.close()


def test_agent_resume_returns_first_pending_question() -> None:
    store, _, _ = make_coach()
    try:
        agent, _ = make_agent(store)
        started = asyncio.run(agent.start())
        first = started.questions[0]
        asyncio.run(agent.submit(started.session_id, first.id, answer_text(first)))

        resumed = agent.resume(started.session_id)
        assert resumed.expired is False
        assert resumed.question is not None
        assert resumed.question["id"] == started.questions[1].id
    finally:
        store.close()


def test_agent_resume_cross_day_expires_and_abandons() -> None:
    store, _, _ = make_coach()
    try:
        agent, _ = make_agent(store, today="2026-11-22")
        started = asyncio.run(agent.start())

        next_day_agent, _ = make_agent(store, today="2026-11-23")
        resumed = next_day_agent.resume(started.session_id)
        assert resumed.expired is True
        old = store.agent_session(started.session_id)
        assert old is not None
        assert old["status"] == "abandoned"
    finally:
        store.close()


def test_agent_probe_once_then_skip() -> None:
    store, _, _ = make_coach()
    try:
        agent, _ = make_agent(store)
        started = asyncio.run(agent.start())
        question = started.questions[0]

        first = asyncio.run(agent.submit(started.session_id, question.id, "知道了"))
        assert first.kind == "probe"
        assert first.probe
        assert first.answer is None

        second = asyncio.run(agent.submit(started.session_id, question.id, "知道了"))
        assert second.kind == "skipped"
        assert second.next_question is not None
        assert second.next_question["id"] == started.questions[1].id

        notes = [n for n in store.session_notes(started.session_id) if n["question_id"] == question.id]
        probes = [n for n in notes if n["output_text"] != "已跳过"]
        assert len(probes) == 1
        assert any(n["output_text"] == "已跳过" for n in notes)
        row = store.question(question.id)
        assert row is not None
        assert row["score"] is None
        assert row["answer_text"] is None
    finally:
        store.close()


def test_agent_probe_falls_back_to_template() -> None:
    store, _, _ = make_coach()
    try:
        agent, _ = make_agent(store, llm=ScriptedLLM(error=RuntimeError("llm down")))
        started = asyncio.run(agent.start())
        question = started.questions[0]
        turn = asyncio.run(agent.submit(started.session_id, question.id, "知道了"))
        assert turn.kind == "probe"
        assert turn.probe == "能举个例子吗？"
    finally:
        store.close()


def test_agent_unknown_scores_zero() -> None:
    store, _, _ = make_coach()
    try:
        agent, _ = make_agent(store)
        started = asyncio.run(agent.start())
        question = started.questions[0]
        turn = asyncio.run(agent.submit(started.session_id, question.id, "不知道"))
        assert turn.kind == "scored"
        assert turn.answer is not None
        assert turn.answer.score == 0
    finally:
        store.close()


def test_agent_skip_advances_without_scoring() -> None:
    store, _, _ = make_coach()
    try:
        agent, _ = make_agent(store)
        started = asyncio.run(agent.start())
        first, second = started.questions[0], started.questions[1]

        turn = agent.skip(started.session_id, first.id)
        assert turn.kind == "skipped"
        assert turn.next_question is not None
        assert turn.next_question["id"] == second.id

        row = store.question(first.id)
        assert row is not None
        assert row["score"] is None
        assert row["answer_text"] is None

        again = agent.skip(started.session_id, first.id)
        assert again.next_question is not None
        assert again.next_question["id"] == second.id
        skip_notes = [
            note
            for note in store.session_notes(started.session_id)
            if note["question_id"] == first.id
            and note["output_text"] == "已跳过"
        ]
        assert len(skip_notes) == 1
    finally:
        store.close()


def test_agent_skip_all_settles_unscored() -> None:
    store, _, _ = make_coach()
    try:
        agent, _ = make_agent(store)
        started = asyncio.run(agent.start())
        last = None
        for question in started.questions:
            last = agent.skip(started.session_id, question.id)
        assert last is not None
        assert last.kind == "settled"
        assert last.settlement is not None
        assert last.settlement.status == "unscored"
    finally:
        store.close()
