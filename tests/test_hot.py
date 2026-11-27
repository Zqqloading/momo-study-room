from __future__ import annotations

from pathlib import Path

import pytest

from core.db import connect, init_schema
from core.store import Store


def make_store() -> Store:
    conn = connect(":memory:")
    init_schema(conn)
    return Store(conn)


def test_capture_dedup_and_normalize() -> None:
    store = make_store()
    try:
        first = store.capture_hot_item(
            source_kind="session",
            text="  光合作用  把光能转成化学能 ",
            text_origin="user",
        )
        second = store.capture_hot_item(
            source_kind="session",
            text="光合作用 把光能转成化学能",
            text_origin="user",
        )
        assert first == second
        item = store.hot_item(first)
        assert item is not None
        assert item.seen_count == 2
        assert item.verified is False
        assert item.status == "hot"
    finally:
        store.close()


def test_capture_rejects_agent_generated_text() -> None:
    store = make_store()
    try:
        with pytest.raises(ValueError):
            store.capture_hot_item(
                source_kind="session", text="模型生成的回答", text_origin="agent"
            )
    finally:
        store.close()


def test_hot_query_filters_discarded_and_expired() -> None:
    store = make_store()
    try:
        hot = store.capture_hot_item(
            source_kind="session",
            text="光合作用把光能转成化学能",
            text_origin="user",
        )
        assert [item.id for item in store.hot_items_for_query("光合作用")] == [hot]

        assert store.discard_hot_item(hot) is True
        assert store.hot_items_for_query("光合作用") == []

        expired = store.capture_hot_item(
            source_kind="agent",
            text="呼吸作用把有机物分解成二氧化碳",
            text_origin="question",
            ttl_days=-1,
        )
        assert store.hot_items_for_query("呼吸作用") == []
        assert store.expire_hot_items() == 1
        item = store.hot_item(expired)
        assert item is not None
        assert item.status == "expired"
    finally:
        store.close()


def test_list_hot_items_only_unexpired_hot() -> None:
    store = make_store()
    try:
        kept = store.capture_hot_item(
            source_kind="session", text="光合作用把光能转成化学能", text_origin="user"
        )
        store.capture_hot_item(
            source_kind="agent",
            text="呼吸作用把有机物分解成二氧化碳",
            text_origin="question",
            ttl_days=-1,
        )
        assert [item.id for item in store.list_hot_items()] == [kept]
    finally:
        store.close()


def test_hot_results_stay_out_of_concept_sources() -> None:
    store = make_store()
    try:
        store.capture_hot_item(
            source_kind="session", text="光合作用把光能转成化学能", text_origin="user"
        )
        hits = store.hot_items_for_query("光合作用")
        assert hits
        count = store.conn.execute(
            "SELECT COUNT(*) AS n FROM concept_sources"
        ).fetchone()["n"]
        assert count == 0
    finally:
        store.close()


def test_hot_cli_capture_list_discard(tmp_path: Path, capsys) -> None:
    from core.hot import main

    db = tmp_path / "app.db"
    assert (
        main(["--db", str(db), "capture", "光合作用把光能转成化学能", "--origin", "user"])
        == 0
    )
    captured = capsys.readouterr().out
    assert captured.startswith("hot=")
    hot_id = int(captured.strip().split("=", 1)[1])

    assert main(["--db", str(db), "list"]) == 0
    listing = capsys.readouterr().out
    assert f"#{hot_id}" in listing
    assert "光合作用" in listing

    assert main(["--db", str(db), "discard", str(hot_id)]) == 0
    assert main(["--db", str(db), "list"]) == 0
    assert "没有未过期的热项" in capsys.readouterr().out
