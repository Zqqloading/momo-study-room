"""查询侧检索封装：概念 → query 文本 → 异步嵌入 → Retriever。

BFF 是组装根：这里才把异步 `Embedder` 和同步 `Retriever` 接起来。
embedding 失败时退回 FTS-only，不阻塞出题。
"""

from __future__ import annotations

from core.concepts import Concept
from core.ports import Embedder
from core.retrieval import Retriever, RetrievedChunk
from core.store import Store


def query_text(concept: Concept) -> str:
    parts = [concept.name, *concept.aliases, concept.plain_def]
    return " ".join(part for part in parts if part)


async def retrieve_concept(
    store: Store,
    embedder: Embedder,
    concept: Concept,
    *,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    query = query_text(concept)
    query_vector = None
    try:
        vectors = await embedder.embed([query])
        if vectors:
            query_vector = vectors[0]
    except Exception:
        query_vector = None

    retriever = Retriever(store, model=embedder.model, dim=embedder.dim)
    return retriever.search(
        query,
        query_vector=query_vector,
        concept_id=concept.id,
        top_k=top_k,
    )


async def retrieve_text(
    store: Store,
    embedder: Embedder,
    text: str,
    *,
    top_k: int = 3,
) -> list[RetrievedChunk]:
    """自由对话用：query 就是用户这句话，嵌入一次后走同一套 Retriever。"""
    query_vector = None
    try:
        vectors = await embedder.embed([text])
        if vectors:
            query_vector = vectors[0]
    except Exception:
        query_vector = None

    retriever = Retriever(store, model=embedder.model, dim=embedder.dim)
    return retriever.search(text, query_vector=query_vector, top_k=top_k)


def is_grounded(hits: list[RetrievedChunk], *, min_cosine: float) -> bool:
    """关键词命中即算有依据；否则看最高余弦是否过阈值。"""
    if not hits:
        return False
    if any(hit.fts_hit for hit in hits):
        return True
    best = max((hit.vector_score or 0.0) for hit in hits)
    return best >= min_cosine


def sources_payload(hits: list[RetrievedChunk]) -> list[dict[str, object]]:
    return [
        {
            "index": index,
            "title": _source_title(hit),
            "url": hit.source_url,
            "excerpt": hit.source_excerpt,
            "kind": "material",
            "domain": "",
            "published_at": None,
            "retrieved_at": None,
        }
        for index, hit in enumerate(hits, start=1)
    ]


def _source_title(hit: RetrievedChunk) -> str:
    if hit.concept_id:
        return hit.concept_id
    name = hit.source_url.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name.rsplit(".", 1)[0] or "材料"
