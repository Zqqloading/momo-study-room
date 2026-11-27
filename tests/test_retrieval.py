from __future__ import annotations

import numpy as np

from core.db import connect, init_schema
from core.retrieval import Retriever, best_excerpt, rrf_fuse
from core.store import Store

PARENT = "Agent 基础"
CHILD_ONE = "工具调用让模型调用外部工具"
CHILD_TWO = "上下文窗口是模型一次能看到的 token 上限"


def make_store() -> Store:
    conn = connect(":memory:")
    init_schema(conn)
    return Store(conn)


def add_material(store: Store, version: int = 1) -> None:
    store.upsert_material(
        material_id="m",
        title="M",
        path="materials/m.md",
        format="md",
        content_hash=f"h{version}",
        version=version,
        added_at="2026-11-23T00:00:00",
        status="active",
        source_url="https://example.com/m",
        tags_json=None,
    )


def add_chunks(
    store: Store,
    version: int = 1,
    *,
    child_one: str = CHILD_ONE,
    child_two: str = CHILD_TWO,
) -> None:
    parent_id = f"m-v{version}-parent-001"
    store.insert_chunks(
        [
            {
                "id": parent_id,
                "material_id": "m",
                "material_version": version,
                "parent_id": None,
                "level": "parent",
                "heading_path": PARENT,
                "text": f"{PARENT} v{version}",
                "content_hash": f"p{version}",
                "token_count": 10,
                "ordinal": 1,
                "source_url": "https://example.com/m",
            },
            {
                "id": f"m-v{version}-child-002",
                "material_id": "m",
                "material_version": version,
                "parent_id": parent_id,
                "level": "child",
                "heading_path": "工具调用",
                "text": child_one,
                "content_hash": f"c1-{version}",
                "token_count": 10,
                "ordinal": 2,
                "source_url": "https://example.com/m",
            },
            {
                "id": f"m-v{version}-child-003",
                "material_id": "m",
                "material_version": version,
                "parent_id": parent_id,
                "level": "child",
                "heading_path": "上下文窗口",
                "text": child_two,
                "content_hash": f"c2-{version}",
                "token_count": 10,
                "ordinal": 3,
                "source_url": "https://example.com/m",
            },
        ]
    )


def embed(store: Store, chunk_id: str, vector: list[float]) -> None:
    store.upsert_embedding(
        chunk_id=chunk_id,
        model="fake",
        dim=3,
        vector=np.asarray(vector, dtype=np.float32).tobytes(),
        created_at="2026-11-23T00:00:00",
    )


def test_rrf_fuse_orders_by_combined_rank() -> None:
    fused = rrf_fuse([["a", "b"], ["a"]], k=60)
    assert [chunk_id for chunk_id, _ in fused] == ["a", "b"]


def test_best_excerpt_skips_overlap_fragment() -> None:
    text = "个部分。\n工具调用让模型调用外部工具。"
    assert (
        best_excerpt(text, "工具调用 function calling 让模型调用外部工具")
        == "工具调用让模型调用外部工具。"
    )


def test_best_excerpt_falls_back_to_parent() -> None:
    child = "决售后问题）"
    parent = "不加料的清汤面-模型会有额外发挥（突然给你加浇头）"
    query = "模型自作主张 大模型会自作主张加需求或改需求"
    assert best_excerpt(child, query, fallback=parent) == parent


def test_ambiguous_parent_needs_concept_hint() -> None:
    store = make_store()
    try:
        add_material(store)
        add_chunks(store)
        embed(store, "m-v1-child-002", [1, 0, 0])
        store.rebuild_fts()
        store.upsert_concept_source(
            concept_id="concept-a", chunk_id="m-v1-parent-001", excerpt="A 的摘录"
        )
        store.upsert_concept_source(
            concept_id="concept-b", chunk_id="m-v1-parent-001", excerpt="B 的摘录"
        )

        assert store.concept_id_for_chunk("m-v1-child-002") is None
        results = Retriever(store, model="fake", dim=3).search(
            "工具调用", query_vector=[1, 0, 0], concept_id="concept-a"
        )
        assert results[0].concept_id == "concept-a"
        assert results[0].source_excerpt == "A 的摘录"
    finally:
        store.close()


def test_concept_source_on_parent_maps_to_child() -> None:
    store = make_store()
    try:
        add_material(store)
        add_chunks(store)
        embed(store, "m-v1-child-002", [1, 0, 0])
        store.rebuild_fts()
        store.upsert_concept_source(
            concept_id="tool-calling",
            chunk_id="m-v1-parent-001",
            excerpt="父块里的概念摘录",
        )

        results = Retriever(store, model="fake", dim=3).search(
            "工具调用", query_vector=[1, 0, 0]
        )
        assert results[0].concept_id == "tool-calling"
        assert results[0].source_excerpt == "父块里的概念摘录"
    finally:
        store.close()


def test_search_backtracks_parent_and_dedups() -> None:
    store = make_store()
    try:
        add_material(store)
        add_chunks(store)
        embed(store, "m-v1-child-002", [1, 0, 0])
        embed(store, "m-v1-child-003", [0, 1, 0])
        store.rebuild_fts()
        store.upsert_concept_source(
            concept_id="tool-calling",
            chunk_id="m-v1-child-002",
            excerpt=CHILD_ONE,
        )

        results = Retriever(store, model="fake", dim=3).search(
            "工具调用", query_vector=[1, 0, 0]
        )

        assert len(results) == 1
        assert results[0].text == f"{PARENT} v1"
        assert results[0].source_excerpt == CHILD_ONE
        assert results[0].source_url == "https://example.com/m"
        assert results[0].concept_id == "tool-calling"
        assert results[0].chunk_id == "m-v1-child-002"
        assert results[0].parent_chunk_id == "m-v1-parent-001"
        assert results[0].score > 0
    finally:
        store.close()


def test_fts_only_and_vector_only_paths() -> None:
    store = make_store()
    try:
        add_material(store)
        add_chunks(store)
        embed(store, "m-v1-child-002", [1, 0, 0])
        embed(store, "m-v1-child-003", [0, 1, 0])
        store.rebuild_fts()
        retriever = Retriever(store, model="fake", dim=3)

        fts_only = retriever.search("工具调用")
        assert len(fts_only) == 1
        assert fts_only[0].source_excerpt == CHILD_ONE

        vector_only = retriever.search("不存在的词", query_vector=[0, 1, 0])
        assert len(vector_only) == 1
        assert vector_only[0].source_excerpt == CHILD_TWO

        assert retriever.search("不存在的词") == []
    finally:
        store.close()


def test_latest_material_version_filters_old_chunks() -> None:
    store = make_store()
    try:
        add_material(store, version=1)
        add_chunks(store, version=1)
        embed(store, "m-v1-child-002", [1, 0, 0])

        add_material(store, version=2)
        add_chunks(store, version=2, child_one="工具调用新版本", child_two="上下文窗口新版本")
        embed(store, "m-v2-child-002", [1, 0, 0])
        store.rebuild_fts()

        results = Retriever(store, model="fake", dim=3).search(
            "工具调用", query_vector=[1, 0, 0]
        )

        assert len(results) == 1
        assert results[0].source_excerpt == "工具调用新版本"
    finally:
        store.close()


def test_fts_failure_falls_back_to_vector(monkeypatch) -> None:
    store = make_store()
    try:
        add_material(store)
        add_chunks(store)
        embed(store, "m-v1-child-002", [1, 0, 0])
        store.rebuild_fts()

        def broken(*args, **kwargs):
            raise RuntimeError("fts down")

        monkeypatch.setattr(store, "search_fts", broken)
        results = Retriever(store, model="fake", dim=3).search(
            "工具调用", query_vector=[1, 0, 0]
        )
        assert len(results) == 1
        assert results[0].source_excerpt == CHILD_ONE
    finally:
        store.close()


def test_missing_embeddings_and_fts_rebuild_count() -> None:
    store = make_store()
    try:
        add_material(store)
        add_chunks(store)
        assert {row["id"] for row in store.missing_embedding_chunks("fake", 3)} == {
            "m-v1-child-002",
            "m-v1-child-003",
        }
        embed(store, "m-v1-child-002", [1, 0, 0])
        assert [row["id"] for row in store.missing_embedding_chunks("fake", 3)] == [
            "m-v1-child-003"
        ]
        assert store.rebuild_fts() == 2
    finally:
        store.close()


def test_short_terms_fall_back_to_substring() -> None:
    store = make_store()
    try:
        add_material(store)
        add_chunks(store)
        store.rebuild_fts()
        assert [chunk_id for chunk_id, _ in store.search_fts("工具", 5)] == [
            "m-v1-child-002"
        ]
        assert [chunk_id for chunk_id, _ in store.search_fts("上下文", 5)] == [
            "m-v1-child-003"
        ]
    finally:
        store.close()
