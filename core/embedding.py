"""批量嵌入与回填（KB-34）。

每批 10 个 chunk；单批失败重试一次；仍失败只记录，不阻塞入库/重建。
补向量前先按 `content_hash + model + dim + heading_path` 复用库中已有向量。
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

import numpy as np

from .ports import Embedder
from .store import Store

BATCH_SIZE = 10


async def embed_chunks(
    store: Store,
    embedder: Embedder,
    rows: Sequence[dict[str, object]],
    *,
    batch_size: int = BATCH_SIZE,
) -> tuple[int, list[str]]:
    embedded = 0
    failures: list[str] = []
    for start in range(0, len(rows), batch_size):
        batch = list(rows[start : start + batch_size])

        pending: list[dict[str, object]] = []
        reused: list[tuple[str, bytes]] = []
        for row in batch:
            vector = _reusable_vector(store, embedder, row)
            if vector is None:
                pending.append(row)
            else:
                reused.append((str(row["id"]), vector))

        if reused:
            created_at = datetime.now().isoformat(timespec="seconds")
            with store.transaction():
                for chunk_id, vector in reused:
                    store.upsert_embedding(
                        chunk_id=chunk_id,
                        model=embedder.model,
                        dim=embedder.dim,
                        vector=vector,
                        created_at=created_at,
                    )
            embedded += len(reused)
        if not pending:
            continue

        vectors = await _embed_with_retry(embedder, [_text(row) for row in pending])
        if (
            vectors is None
            or len(vectors) != len(pending)
            or any(len(vector) != embedder.dim for vector in vectors)
        ):
            failures.extend(str(row["id"]) for row in pending)
            continue

        created_at = datetime.now().isoformat(timespec="seconds")
        with store.transaction():
            for row, vector in zip(pending, vectors):
                store.upsert_embedding(
                    chunk_id=str(row["id"]),
                    model=embedder.model,
                    dim=embedder.dim,
                    vector=np.asarray(vector, dtype=np.float32).tobytes(),
                    created_at=created_at,
                )
        embedded += len(pending)
    return embedded, failures


def _reusable_vector(
    store: Store, embedder: Embedder, row: dict[str, object]
) -> bytes | None:
    content_hash = row.get("content_hash")
    if not content_hash:
        return None
    return store.embedding_by_content_hash(
        str(content_hash),
        embedder.model,
        embedder.dim,
        str(row.get("heading_path") or ""),
    )


async def embed_missing(
    store: Store,
    embedder: Embedder,
    *,
    batch_size: int = BATCH_SIZE,
) -> tuple[int, list[str]]:
    rows = store.missing_embedding_chunks(embedder.model, embedder.dim)
    return await embed_chunks(store, embedder, rows, batch_size=batch_size)


async def _embed_with_retry(
    embedder: Embedder, texts: Sequence[str]
) -> list[list[float]] | None:
    for attempt in range(2):
        try:
            return await embedder.embed(texts)
        except Exception:
            if attempt == 1:
                return None
    return None


def _text(row: dict[str, object]) -> str:
    heading = str(row.get("heading_path") or "")
    body = str(row["text"])
    return f"{heading}\n{body}" if heading else body
