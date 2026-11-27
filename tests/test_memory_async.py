from __future__ import annotations

import asyncio
from datetime import datetime

from bff.memory_extraction import MemoryExtractor
from core.db import connect, init_schema
from core.store import Store

NOW = datetime(2026, 11, 26, 10, 0, 0)


class _ScriptedScorer:
    name = "scripted-memory"

    def __init__(self, *payloads: str) -> None:
        self.payloads = list(payloads)
        self.calls = 0

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        if not self.payloads:
            return '{"memories":[]}'
        return self.payloads.pop(0)


def _seed_session(store: Store) -> int:
    store.start_agent_session(
        session_id="s1",
        kind="daily",
        date="2026-11-26",
        started_at="2026-11-26T10:00:00",
    )
    question_id = store.add_question(
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
    store.save_answer(
        question_id,
        text="我更喜欢先看例子，再看定义",
        score=70,
        feedback="好",
    )
    return question_id


def _extractor(store: Store, scorer) -> MemoryExtractor:
    return MemoryExtractor(
        store,
        scorer,
        user_id="owner",
        clock=lambda: NOW,
        rng=lambda low, high: 1.0,
    )


def test_run_writes_memories_and_audit() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        _seed_session(store)
        scorer = _ScriptedScorer(
            '{"memories":['
            '{"kind":"preference","text":"更习惯先看例子",'
            '"source_quote":"更喜欢先看例子"},'
            '{"kind":"quote","text":"先看例子再看定义",'
            '"source_quote":"我更喜欢先看例子，再看定义"}'
            ']}'
        )
        asyncio.run(_extractor(store, scorer).run("s1"))

        rows = store.user_memories("owner")
        assert [(row["kind"], row["text"]) for row in rows] == [
            ("preference", "更习惯先看例子"),
            ("quote", "先看例子再看定义"),
        ]
        assert rows[0]["source_question_id"] == 1
        run = store.memory_run_for_session("owner", "s1")
        assert run is not None
        assert run["status"] == "succeeded"
        assert run["memory_count"] == 2
        assert scorer.calls == 1
    finally:
        store.close()


def test_run_without_user_text_is_empty() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        store.start_agent_session(
            session_id="s1",
            kind="daily",
            date="2026-11-26",
            started_at="2026-11-26T10:00:00",
        )
        scorer = _ScriptedScorer()
        asyncio.run(_extractor(store, scorer).run("s1"))
        assert store.user_memories("owner") == []
        run = store.memory_run_for_session("owner", "s1")
        assert run is not None
        assert run["status"] == "empty"
        assert scorer.calls == 0
    finally:
        store.close()


def test_run_retries_once_then_succeeds() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        _seed_session(store)
        scorer = _ScriptedScorer(
            "不是 JSON",
            '{"memories":[{"kind":"quote","text":"怕公式",'
            '"source_quote":"我更喜欢先看例子"}]}',
        )
        asyncio.run(_extractor(store, scorer).run("s1"))
        assert scorer.calls == 2
        assert [row["text"] for row in store.user_memories("owner")] == ["怕公式"]
        run = store.memory_run_for_session("owner", "s1")
        assert run is not None
        assert run["status"] == "succeeded"
    finally:
        store.close()


def test_run_fails_after_one_retry() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        _seed_session(store)
        scorer = _ScriptedScorer("不是 JSON", "还不是 JSON")
        asyncio.run(_extractor(store, scorer).run("s1"))
        assert scorer.calls == 2
        assert store.user_memories("owner") == []
        run = store.memory_run_for_session("owner", "s1")
        assert run is not None
        assert run["status"] == "failed"
        assert run["error"]
    finally:
        store.close()


def test_duplicate_memory_merges_as_explicit_recall() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        _seed_session(store)
        existing_id = store.add_user_memory(
            user_id="owner",
            kind="preference",
            text="更习惯先看例子",
            source_quote="我更喜欢先看例子，再看定义",
            source_session_id="s0",
            source_question_id=None,
            strength=0.5,
            half_life_days=14.0,
            last_recalled_at="2026-11-01T10:00:00",
            created_at="2026-11-01T10:00:00",
        )
        scorer = _ScriptedScorer(
            '{"memories":[{"kind":"preference","text":"更习惯先看例子",'
            '"source_quote":"我更喜欢先看例子，再看定义"}]}'
        )
        asyncio.run(_extractor(store, scorer).run("s1"))

        rows = store.user_memories("owner")
        assert len(rows) == 1
        assert rows[0]["id"] == existing_id
        assert rows[0]["recall_count"] == 1
        assert rows[0]["strength"] >= 0.1
        assert rows[0]["last_recalled_at"] == "2026-11-26T10:00:00"
    finally:
        store.close()


def test_second_run_is_skipped() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        _seed_session(store)
        scorer = _ScriptedScorer(
            '{"memories":[{"kind":"quote","text":"怕公式",'
            '"source_quote":"我更喜欢先看例子"}]}'
        )
        extractor = _extractor(store, scorer)
        asyncio.run(extractor.run("s1"))
        asyncio.run(extractor.run("s1"))
        assert scorer.calls == 1
        assert len(store.user_memories("owner")) == 1
    finally:
        store.close()


def test_non_substring_quote_yields_empty() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        _seed_session(store)
        scorer = _ScriptedScorer(
            '{"memories":[{"kind":"quote","text":"怕公式",'
            '"source_quote":"我特别怕公式"}]}'
        )
        asyncio.run(_extractor(store, scorer).run("s1"))
        assert store.user_memories("owner") == []
        run = store.memory_run_for_session("owner", "s1")
        assert run is not None
        assert run["status"] == "empty"
    finally:
        store.close()
