from __future__ import annotations

import asyncio

from core.db import connect, init_schema
from core.embedding import embed_chunks, embed_missing
from core.store import Store


class GoodEmbedder:
    name = "good"
    model = "fake"
    dim = 4

    async def embed(self, texts):
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class FlakyEmbedder(GoodEmbedder):
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("boom")
        return await super().embed(texts)


class FailEmbedder(GoodEmbedder):
    async def embed(self, texts):
        raise RuntimeError("down")


class MismatchEmbedder(GoodEmbedder):
    async def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


def make_store() -> Store:
    conn = connect(":memory:")
    init_schema(conn)
    return Store(conn)


def add_chunks(store: Store) -> None:
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
                "heading_path": "H",
                "text": "parent",
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
                "heading_path": "H",
                "text": "child one",
                "content_hash": "c1",
                "token_count": 1,
                "ordinal": 2,
                "source_url": "https://example.com/m",
            },
            {
                "id": "m-v1-child-003",
                "material_id": "m",
                "material_version": 1,
                "parent_id": parent_id,
                "level": "child",
                "heading_path": "H",
                "text": "child two",
                "content_hash": "c2",
                "token_count": 1,
                "ordinal": 3,
                "source_url": "https://example.com/m",
            },
        ]
    )


def rows() -> list[dict[str, object]]:
    return [
        {"id": "m-v1-child-002", "heading_path": "H", "text": "child one"},
        {"id": "m-v1-child-003", "heading_path": "H", "text": "child two"},
    ]


def test_embed_chunks_writes_vectors() -> None:
    store = make_store()
    try:
        add_chunks(store)
        embedded, failures = asyncio.run(embed_chunks(store, GoodEmbedder(), rows()))
        assert embedded == 2
        assert failures == []
        assert {row["chunk_id"] for row in store.embeddings_latest("fake", 4)} == {
            "m-v1-child-002",
            "m-v1-child-003",
        }
    finally:
        store.close()


def test_batch_retries_once() -> None:
    store = make_store()
    try:
        add_chunks(store)
        embedder = FlakyEmbedder()
        embedded, failures = asyncio.run(embed_chunks(store, embedder, rows()))
        assert embedder.calls == 2
        assert embedded == 2
        assert failures == []
    finally:
        store.close()


def test_failed_batch_writes_nothing() -> None:
    store = make_store()
    try:
        add_chunks(store)
        embedded, failures = asyncio.run(embed_chunks(store, FailEmbedder(), rows()))
        assert embedded == 0
        assert sorted(failures) == ["m-v1-child-002", "m-v1-child-003"]
        assert store.embeddings_latest("fake", 4) == []
    finally:
        store.close()


def test_dimension_mismatch_is_failure() -> None:
    store = make_store()
    try:
        add_chunks(store)
        embedded, failures = asyncio.run(embed_chunks(store, MismatchEmbedder(), rows()))
        assert embedded == 0
        assert len(failures) == 2
        assert store.embeddings_latest("fake", 4) == []
    finally:
        store.close()


def test_embed_missing_only_fills_missing() -> None:
    store = make_store()
    try:
        add_chunks(store)
        asyncio.run(embed_chunks(store, GoodEmbedder(), rows()[:1]))
        embedded, failures = asyncio.run(embed_missing(store, GoodEmbedder()))
        assert embedded == 1
        assert failures == []
        assert store.missing_embedding_chunks("fake", 4) == []
    finally:
        store.close()


class CountingEmbedder(GoodEmbedder):
    def __init__(self) -> None:
        self.texts = 0

    async def embed(self, texts):
        self.texts += len(texts)
        return await super().embed(texts)


def bump_to_v2(store: Store) -> None:
    store.upsert_material(
        material_id="m",
        title="M",
        path="materials/m.md",
        format="md",
        content_hash="h2",
        version=2,
        added_at="2026-11-23T00:00:00",
        status="active",
        source_url="https://example.com/m",
        tags_json=None,
    )
    parent_id = "m-v2-parent-001"
    store.insert_chunks(
        [
            {
                "id": parent_id,
                "material_id": "m",
                "material_version": 2,
                "parent_id": None,
                "level": "parent",
                "heading_path": "H",
                "text": "parent",
                "content_hash": "p",
                "token_count": 1,
                "ordinal": 1,
                "source_url": "https://example.com/m",
            },
            {
                "id": "m-v2-child-002",
                "material_id": "m",
                "material_version": 2,
                "parent_id": parent_id,
                "level": "child",
                "heading_path": "H",
                "text": "child one",
                "content_hash": "c1",
                "token_count": 1,
                "ordinal": 2,
                "source_url": "https://example.com/m",
            },
            {
                "id": "m-v2-child-003",
                "material_id": "m",
                "material_version": 2,
                "parent_id": parent_id,
                "level": "child",
                "heading_path": "H",
                "text": "child three",
                "content_hash": "c3",
                "token_count": 1,
                "ordinal": 3,
                "source_url": "https://example.com/m",
            },
        ]
    )


def test_embedding_reuses_same_content_hash_and_heading() -> None:
    store = make_store()
    try:
        add_chunks(store)
        first = CountingEmbedder()
        embedded, failures = asyncio.run(
            embed_chunks(store, first, store.missing_embedding_chunks("fake", 4))
        )
        assert embedded == 2
        assert failures == []
        assert first.texts == 2

        bump_to_v2(store)
        second = CountingEmbedder()
        embedded, failures = asyncio.run(embed_missing(store, second))
        assert embedded == 2
        assert failures == []
        assert second.texts == 1

        v1 = store.conn.execute(
            "SELECT vector FROM chunk_embeddings WHERE chunk_id = 'm-v1-child-002'"
        ).fetchone()["vector"]
        v2 = store.conn.execute(
            "SELECT vector FROM chunk_embeddings WHERE chunk_id = 'm-v2-child-002'"
        ).fetchone()["vector"]
        assert v1 == v2
    finally:
        store.close()


def test_prune_index_orphans_keeps_chunk_rows() -> None:
    store = make_store()
    try:
        add_chunks(store)
        asyncio.run(
            embed_chunks(store, GoodEmbedder(), store.missing_embedding_chunks("fake", 4))
        )
        bump_to_v2(store)
        store.rebuild_fts()
        store.upsert_embedding(
            chunk_id="ghost", model="fake", dim=4, vector=b"x", created_at="2026-11-23"
        )
        store.conn.execute(
            """
            INSERT INTO chunk_fts (chunk_id, material_id, material_version, text)
            VALUES ('ghost', 'm', 1, 'ghost text')
            """
        )

        pruned_embeddings, pruned_fts = store.prune_index_orphans()

        assert pruned_embeddings == 1
        assert pruned_fts == 1
        old_version = store.conn.execute(
            """
            SELECT COUNT(*) AS n FROM chunk_embeddings
            WHERE chunk_id IN ('m-v1-child-002', 'm-v1-child-003')
            """
        ).fetchone()["n"]
        assert old_version == 2
        assert (
            store.conn.execute(
                "SELECT COUNT(*) AS n FROM chunk_embeddings WHERE chunk_id = 'ghost'"
            ).fetchone()["n"]
            == 0
        )
    finally:
        store.close()
