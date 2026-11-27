from __future__ import annotations

from core.db import connect, init_schema
from core.store import Store


def _store() -> Store:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    return store


def _add(
    store: Store,
    *,
    kind: str = "quote",
    text: str = "怕公式",
    source_quote: str = "我有点怕公式",
    strength: float = 1.0,
    last_recalled_at: str = "2026-11-26T10:00:00",
    user_id: str = "owner",
) -> int:
    return store.add_user_memory(
        user_id=user_id,
        kind=kind,
        text=text,
        source_quote=source_quote,
        source_session_id="s1",
        source_question_id=1,
        strength=strength,
        half_life_days=14.0,
        last_recalled_at=last_recalled_at,
        created_at="2026-11-26T10:00:00",
    )


def test_add_and_read_memory() -> None:
    store = _store()
    try:
        memory_id = _add(store)
        rows = store.user_memories("owner")
        assert [row["id"] for row in rows] == [memory_id]
        assert rows[0]["text"] == "怕公式"
        assert rows[0]["user_id"] == "owner"
        assert store.user_memories("other") == []
    finally:
        store.close()


def test_update_recall_fields() -> None:
    store = _store()
    try:
        memory_id = _add(store)
        store.update_memory_recall(
            memory_id,
            strength=0.5,
            half_life_days=18.0,
            last_recalled_at="2026-11-27T10:00:00",
            recall_count=2,
        )
        row = store.user_memories("owner")[0]
        assert row["strength"] == 0.5
        assert row["half_life_days"] == 18.0
        assert row["last_recalled_at"] == "2026-11-27T10:00:00"
        assert row["recall_count"] == 2
    finally:
        store.close()


def test_fts_finds_three_char_query_even_when_dormant() -> None:
    store = _store()
    try:
        _add(store, strength=0.01, last_recalled_at="2026-08-01T10:00:00")
        rows = store.search_user_memories("owner", "怕公式")
        assert [row["text"] for row in rows] == ["怕公式"]
    finally:
        store.close()


def test_two_char_query_falls_back_to_substring() -> None:
    store = _store()
    try:
        _add(store, text="更习惯先看例子", source_quote="我更喜欢先看例子")
        rows = store.search_user_memories("owner", "喜欢怎么学")
        assert [row["text"] for row in rows] == ["更习惯先看例子"]
        assert rows[0]["score"] > 0
    finally:
        store.close()


def test_search_respects_user_and_limit() -> None:
    store = _store()
    try:
        _add(store, user_id="owner", text="怕公式")
        _add(store, user_id="other", text="怕公式")
        rows = store.search_user_memories("owner", "怕公式", limit=1)
        assert len(rows) == 1
        assert rows[0]["user_id"] == "owner"
    finally:
        store.close()


def test_rebuild_user_memory_fts() -> None:
    store = _store()
    try:
        _add(store)
        store.conn.execute("DELETE FROM user_memories_fts")
        assert (
            store.conn.execute("SELECT COUNT(*) FROM user_memories_fts").fetchone()[0]
            == 0
        )
        assert store.rebuild_user_memory_fts() == 1
        assert (
            store.conn.execute("SELECT COUNT(*) FROM user_memories_fts").fetchone()[0]
            == 1
        )
        assert store.search_user_memories("owner", "怕公式")
    finally:
        store.close()


def test_memory_run_lifecycle() -> None:
    store = _store()
    try:
        assert not store.memory_run_exists("owner", "s1")
        run_id = store.start_memory_run(
            user_id="owner", session_id="s1", started_at="2026-11-26T10:00:00"
        )
        assert store.memory_run_exists("owner", "s1")
        store.finish_memory_run(
            run_id,
            status="succeeded",
            memory_count=2,
            error=None,
            finished_at="2026-11-26T10:01:00",
        )
        row = store.memory_run_for_session("owner", "s1")
        assert row is not None
        assert row["status"] == "succeeded"
        assert row["memory_count"] == 2
        assert row["finished_at"] == "2026-11-26T10:01:00"
    finally:
        store.close()


def test_user_texts_for_session_filters_noise_and_dedupes() -> None:
    store = _store()
    try:
        store.start_agent_session(
            session_id="s1",
            kind="daily",
            date="2026-11-26",
            started_at="2026-11-26T10:00:00",
        )
        first = store.add_question(
            session_id="s1",
            question_bank_id=None,
            concept_id="agent-loop",
            role="new",
            kind="apply",
            question_type="business",
            text="什么是 agent 循环",
            rubric_json={},
            source_url="fixture://q",
            source_excerpt="出处",
            created_at="2026-11-26T10:00:00",
        )
        second = store.add_question(
            session_id="s1",
            question_bank_id=None,
            concept_id="agent-loop",
            role="new",
            kind="apply",
            question_type="business",
            text="解释 workflow",
            rubric_json={},
            source_url="fixture://q2",
            source_excerpt="出处",
            created_at="2026-11-26T10:00:00",
        )
        store.save_answer(first, text="我更喜欢先看例子，再看定义", score=70, feedback="好")
        store.save_answer(second, text="不知道", score=0, feedback="再想想")
        store.add_session_note(
            session_id="s1",
            question_id=first,
            mode="probe",
            input_text="我更喜欢先看例子，再看定义",
            output_text="能举个例子吗？",
            created_at="2026-11-26T10:01:00",
        )
        store.add_session_note(
            session_id="s1",
            question_id=None,
            mode="probe",
            input_text="听到大段定义会有点烦",
            output_text="能举个例子吗？",
            created_at="2026-11-26T10:02:00",
        )
        texts = store.user_texts_for_session("s1")
        assert [item["text"] for item in texts] == [
            "我更喜欢先看例子，再看定义",
            "听到大段定义会有点烦",
        ]
        assert texts[0]["question_id"] == first
        assert texts[0]["question_text"] == "什么是 agent 循环"
        assert texts[1]["question_text"] is None
    finally:
        store.close()
