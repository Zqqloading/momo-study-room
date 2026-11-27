from __future__ import annotations

from datetime import datetime

from bff.memory import MemoryService
from core.db import connect, init_schema
from core.store import Store

NOW = datetime(2026, 11, 26, 10, 0, 0)


def _service(store: Store) -> MemoryService:
    return MemoryService(
        store,
        user_id="owner",
        clock=lambda: NOW,
        rng=lambda low, high: 1.0,
    )


def _add(
    store: Store,
    memory_id_text: str,
    *,
    kind: str = "preference",
    text: str | None = None,
    source_quote: str | None = None,
    strength: float = 1.0,
    last_recalled_at: str = "2026-11-26T10:00:00",
    user_id: str = "owner",
) -> int:
    return store.add_user_memory(
        user_id=user_id,
        kind=kind,
        text=text or memory_id_text,
        source_quote=source_quote or memory_id_text,
        source_session_id="s0",
        source_question_id=None,
        strength=strength,
        half_life_days=14.0,
        last_recalled_at=last_recalled_at,
        created_at=last_recalled_at,
    )


def test_opening_block_selects_and_updates_recall() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        _add(store, "先看例子", text="先看例子", strength=0.9)
        _add(store, "喜欢短例子", text="喜欢短例子", strength=0.6)
        service = _service(store)
        block = service.opening_block(max_chars=300)
        assert block.startswith("先想起几件你说过的事：")
        assert "先看例子" in block
        rows = store.user_memories("owner")
        assert all(row["recall_count"] == 1 for row in rows)
        assert all(row["last_recalled_at"] == "2026-11-26T10:00:00" for row in rows)
    finally:
        store.close()


def test_opening_block_empty_without_memories() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        assert _service(store).opening_block() == ""
    finally:
        store.close()


def test_opening_block_respects_budget() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        for index in range(5):
            _add(store, f"偏好{index}", kind="preference", text="很长的偏好" * 10, strength=0.9)
        block = _service(store).opening_block(max_chars=40)
        assert block == ""
    finally:
        store.close()


def test_recall_without_trigger_returns_none() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        assert _service(store).recall("今天天气不错") is None
    finally:
        store.close()


def test_recall_with_trigger_but_no_hit_returns_empty() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        assert _service(store).recall("你还记得我说过怕公式吗") == ""
    finally:
        store.close()


def test_recall_returns_and_wakes_dormant_memory() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        _add(
            store,
            "怕公式",
            kind="quote",
            text="怕公式",
            source_quote="我有点怕公式",
            strength=0.2,
            last_recalled_at="2026-08-01T10:00:00",
        )
        context = _service(store).recall("你还记得我之前说怕公式吗")
        assert context == "- 怕公式"
        row = store.user_memories("owner")[0]
        assert row["strength"] >= 0.1
        assert row["recall_count"] == 1
        assert row["last_recalled_at"] == "2026-11-26T10:00:00"
    finally:
        store.close()


def test_recall_respects_user() -> None:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    try:
        _add(store, "怕公式", text="怕公式", user_id="other")
        assert _service(store).recall("你还记得我之前说怕公式吗") == ""
    finally:
        store.close()
