from __future__ import annotations

import pytest

from core.db import connect, init_schema
from core.store import Store


def make_store() -> Store:
    conn = connect(":memory:")
    init_schema(conn)
    return Store(conn)


def test_append_messages_sets_title_and_updated_at() -> None:
    store = make_store()
    try:
        store.create_conversation(conversation_id="c1", created_at="2026-11-23T10:00:00")
        store.append_conversation_message(
            conversation_id="c1",
            role="user",
            text="什么是 agent 循环",
            created_at="2026-11-23T10:01:00",
        )
        store.append_conversation_message(
            conversation_id="c1",
            role="assistant",
            text="就是观察、决策、行动反复执行。",
            mode="teach",
            created_at="2026-11-23T10:01:02",
        )

        conversation = store.conversation("c1")
        assert conversation is not None
        assert conversation["title"] == "什么是 agent 循环"
        assert conversation["updated_at"] == "2026-11-23T10:01:02"

        messages = store.conversation_messages("c1")
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert messages[1]["mode"] == "teach"
    finally:
        store.close()


def test_conversations_order_by_latest_and_count_messages() -> None:
    store = make_store()
    try:
        store.create_conversation(conversation_id="old", created_at="2026-11-22T10:00:00")
        store.create_conversation(conversation_id="new", created_at="2026-11-23T10:00:00")
        store.append_conversation_message(
            conversation_id="new",
            role="user",
            text="今天好累",
            created_at="2026-11-23T10:01:00",
        )
        rows = store.conversations()
        assert [row["id"] for row in rows] == ["new", "old"]
        assert rows[0]["message_count"] == 1
        assert rows[1]["message_count"] == 0
        assert store.latest_conversation()["id"] == "new"  # type: ignore[index]
    finally:
        store.close()


def test_rename_and_delete_conversation() -> None:
    store = make_store()
    try:
        store.create_conversation(conversation_id="c1", created_at="2026-11-24T10:00:00")
        store.append_conversation_message(
            conversation_id="c1",
            role="user",
            text="旧标题",
            created_at="2026-11-24T10:00:01",
        )
        store.rename_conversation("c1", "新标题")
        conversation = store.conversation("c1")
        assert conversation is not None
        assert conversation["title"] == "新标题"
        assert conversation["updated_at"] == "2026-11-24T10:00:01"

        store.delete_conversation("c1")
        assert store.conversation("c1") is None
        assert store.conversation_messages("c1") == []
    finally:
        store.close()


def test_recent_messages_returns_last_n_in_order() -> None:
    store = make_store()
    try:
        store.create_conversation(conversation_id="c1", created_at="2026-11-23T10:00:00")
        for index in range(15):
            store.append_conversation_message(
                conversation_id="c1",
                role="user" if index % 2 == 0 else "assistant",
                text=f"m{index}",
                created_at=f"2026-11-23T10:{index:02d}:00",
            )
        recent = store.recent_conversation_messages("c1", limit=12)
        assert len(recent) == 12
        assert recent[0]["text"] == "m3"
        assert recent[-1]["text"] == "m14"
    finally:
        store.close()


def test_append_to_missing_conversation_is_rejected() -> None:
    store = make_store()
    try:
        with pytest.raises(KeyError):
            store.append_conversation_message(
                conversation_id="missing",
                role="user",
                text="hi",
                created_at="2026-11-23T10:00:00",
            )
    finally:
        store.close()


def test_assistant_sources_are_persisted() -> None:
    store = make_store()
    try:
        store.create_conversation(conversation_id="c1", created_at="2026-11-24T10:00:00")
        sources = [
            {
                "index": 1,
                "title": "模型自作主张",
                "url": "local://materials/note.md",
                "excerpt": "大模型会自作主张加需求。",
            }
        ]
        store.append_conversation_message(
            conversation_id="c1",
            role="assistant",
            text="材料里说大模型会发散。",
            mode="teach",
            sources=sources,
            created_at="2026-11-24T10:00:01",
        )
        messages = store.conversation_messages("c1")
        assert messages[0]["sources_json"] is not None
        assert sources[0]["excerpt"] in messages[0]["sources_json"]
    finally:
        store.close()
