from __future__ import annotations

import asyncio

import numpy as np

from bff.retrieval import query_text, retrieve_concept
from core.concepts import Concept, Source
from core.db import connect, init_schema
from core.store import Store

PARENT = "Agent 基础"
CHILD = "工具调用让模型调用外部工具"


class FakeEmbedder:
    name = "fake"
    model = "fake"
    dim = 3

    def __init__(self, vector: list[float] | None = None, *, fail: bool = False) -> None:
        self.vector = vector or [1.0, 0.0, 0.0]
        self.fail = fail
        self.calls = 0

    async def embed(self, texts):
        self.calls += 1
        if self.fail:
            raise RuntimeError("embedding down")
        return [self.vector for _ in texts]


def make_store() -> Store:
    conn = connect(":memory:")
    init_schema(conn)
    store = Store(conn)
    store.upsert_material(
        material_id="m",
        title="M",
        path="materials/m.md",
        format="md",
        content_hash="h",
        version=1,
        added_at="2026-11-23T00:00:00",
        status="active",
        source_url="https://example.com/m",
        tags_json=None,
    )
    parent_id = "m-v1-parent-001"
    store.insert_chunks(
        [
            {
                "id": parent_id,
                "material_id": "m",
                "material_version": 1,
                "parent_id": None,
                "level": "parent",
                "heading_path": PARENT,
                "text": PARENT,
                "content_hash": "p",
                "token_count": 1,
                "ordinal": 1,
                "source_url": "https://example.com/m",
            },
            {
                "id": "m-v1-child-002",
                "material_id": "m",
                "material_version": 1,
                "parent_id": parent_id,
                "level": "child",
                "heading_path": "工具调用",
                "text": CHILD,
                "content_hash": "c",
                "token_count": 1,
                "ordinal": 2,
                "source_url": "https://example.com/m",
            },
        ]
    )
    store.upsert_embedding(
        chunk_id="m-v1-child-002",
        model="fake",
        dim=3,
        vector=np.asarray([1.0, 0.0, 0.0], dtype=np.float32).tobytes(),
        created_at="2026-11-23T00:00:00",
    )
    store.rebuild_fts()
    store.upsert_concept_source(
        concept_id="tool-calling",
        chunk_id="m-v1-child-002",
        excerpt=CHILD,
    )
    return store


def concept() -> Concept:
    return Concept(
        id="tool-calling",
        name="工具调用",
        aliases=("function calling",),
        plain_def="让模型调用外部工具",
        difficulty=2,
        prerequisites=(),
        source=Source(url="https://example.com/m", excerpt=CHILD),
    )


def test_query_text_uses_name_aliases_and_definition() -> None:
    assert query_text(concept()) == "工具调用 function calling 让模型调用外部工具"


def test_retrieve_concept_embeds_and_returns_parent() -> None:
    store = make_store()
    try:
        embedder = FakeEmbedder()
        results = asyncio.run(retrieve_concept(store, embedder, concept()))
        assert embedder.calls == 1
        assert len(results) == 1
        assert results[0].text == PARENT
        assert results[0].source_excerpt == CHILD
        assert results[0].concept_id == "tool-calling"
    finally:
        store.close()


def test_embedding_failure_falls_back_to_fts() -> None:
    store = make_store()
    try:
        embedder = FakeEmbedder(fail=True)
        results = asyncio.run(retrieve_concept(store, embedder, concept()))
        assert results
        assert results[0].source_excerpt == CHILD
    finally:
        store.close()
