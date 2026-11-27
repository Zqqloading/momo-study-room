"""v1 检索：FTS5 trigram + 向量 + RRF（KB-30…KB-35）。

同步 `search`；query 向量由调用方异步算好后传入，避免在异步上下文里跑
``asyncio.run``。两路各自降级：FTS 失败只走向量，向量失败只走 FTS。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .store import Store


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    concept_id: str | None
    text: str
    source_excerpt: str
    source_url: str
    score: float
    chunk_id: str = ""
    parent_chunk_id: str | None = None
    vector_score: float | None = None
    fts_hit: bool = False


def normalize(vector: Sequence[float]) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(array))
    if norm == 0.0:
        return array
    return array / norm


def rrf_fuse(arms: list[list[str]], *, k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for arm in arms:
        for rank, chunk_id in enumerate(arm, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def best_excerpt(
    text: str,
    query: str,
    *,
    fallback: str | None = None,
    max_chars: int = 160,
) -> str:
    """从子块里挑与 query 词面最相关的一句；子块没有就退到父块。"""
    features: set[str] = set()
    for term in query.split():
        if len(term) < 2:
            continue
        features.add(term)
        if re.search(r"[\u4e00-\u9fff]", term):
            features.update(term[index : index + 2] for index in range(len(term) - 1))

    def feature_score(sentence: str) -> int:
        return sum(1 for feature in features if feature in sentence)

    def best_in(candidate_text: str) -> tuple[int, str]:
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[。！？!?])\s*|\n+", candidate_text)
            if sentence.strip()
        ]
        if not sentences:
            return 0, candidate_text[:max_chars]
        ranked = sorted(
            enumerate(sentences),
            key=lambda item: (-feature_score(item[1]), item[0]),
        )
        sentence = ranked[0][1]
        return feature_score(sentence), sentence[:max_chars]

    matched, excerpt = best_in(text)
    if matched > 0:
        return excerpt
    if fallback:
        fallback_matched, fallback_excerpt = best_in(fallback)
        if fallback_matched > 0:
            return fallback_excerpt
    return excerpt


class Retriever:
    def __init__(
        self,
        store: Store,
        *,
        model: str = "text-embedding-v4",
        dim: int = 1024,
        fts_limit: int = 20,
        vector_limit: int = 20,
        rrf_k: int = 60,
    ) -> None:
        self.store = store
        self.model = model
        self.dim = dim
        self.fts_limit = fts_limit
        self.vector_limit = vector_limit
        self.rrf_k = rrf_k

    def search(
        self,
        query: str,
        *,
        query_vector: Sequence[float] | None = None,
        concept_id: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        try:
            fts_ids = [chunk_id for chunk_id, _ in self.store.search_fts(query, self.fts_limit)]
        except Exception:
            fts_ids = []
        try:
            vector_ids, vector_scores = self._vector_ids(query_vector)
        except Exception:
            vector_ids, vector_scores = [], {}

        fused = rrf_fuse([fts_ids, vector_ids], k=self.rrf_k)
        results: list[RetrievedChunk] = []
        seen_parents: set[str] = set()
        for chunk_id, score in fused:
            row = self.store.chunk_with_parent(chunk_id)
            if row is None:
                continue
            parent_key = row["parent_chunk_id"] or chunk_id
            if parent_key in seen_parents:
                continue
            seen_parents.add(parent_key)
            effective_concept = concept_id or self.store.concept_id_for_chunk(chunk_id)
            excerpt = (
                self.store.concept_source_excerpt(effective_concept)
                if effective_concept
                else None
            ) or best_excerpt(
                row["child_text"], query, fallback=row["parent_text"]
            )
            results.append(
                RetrievedChunk(
                    concept_id=effective_concept,
                    text=row["parent_text"] or row["child_text"],
                    source_excerpt=excerpt,
                    source_url=row["parent_url"] or row["child_url"] or "",
                    score=float(score),
                    chunk_id=row["child_id"],
                    parent_chunk_id=row["parent_chunk_id"],
                    vector_score=vector_scores.get(chunk_id),
                    fts_hit=chunk_id in fts_ids,
                )
            )
            if len(results) >= top_k:
                break
        return results

    def _vector_ids(
        self, query_vector: Sequence[float] | None
    ) -> tuple[list[str], dict[str, float]]:
        if query_vector is None:
            return [], {}
        query = normalize(query_vector)
        if query.shape[0] != self.dim:
            return [], {}

        rows = self.store.embeddings_latest(self.model, self.dim)
        ids: list[str] = []
        vectors: list[np.ndarray] = []
        for row in rows:
            vector = np.frombuffer(row["vector"], dtype=np.float32)
            if vector.shape[0] != self.dim:
                continue
            ids.append(row["chunk_id"])
            vectors.append(vector)
        if not ids:
            return [], {}

        matrix = np.vstack(vectors)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms != 0)
        scores = matrix @ query
        order = np.argsort(-scores)[: self.vector_limit]
        ordered = [ids[int(index)] for index in order]
        return ordered, {chunk_id: float(scores[int(index)]) for chunk_id, index in zip(ordered, order)}
