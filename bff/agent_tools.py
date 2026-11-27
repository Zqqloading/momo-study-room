"""BFF 侧工具适配器：把本地检索、网页搜索与概念表接到 core 契约。

工具只读；不写数据库、不生成题、不评分。
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from core.agent_tools import (
    CODE_INVALID_ARGUMENTS,
    CODE_NOT_CONFIGURED,
    CODE_NOT_FOUND,
    CODE_PROVIDER_ERROR,
    CODE_TIMEOUT,
    DEFAULT_TOOL_SPECS,
    MAX_MATERIAL_CHARS,
    MAX_MATERIAL_RESULTS,
    MAX_WEB_CHARS,
    MAX_WEB_RESULTS,
    TOOL_READ_CONCEPT,
    TOOL_SEARCH_MATERIALS,
    TOOL_SEARCH_WEB,
    ToolRegistry,
    ToolResult,
    clip_text,
)
from core.concepts import Concept
from core.ports import Embedder, SearchHit, SearchProvider
from core.retrieval import RetrievedChunk
from core.store import Store

from .retrieval import is_grounded, retrieve_text
from .web_sources import domain_of, filter_web_results, web_sources_payload

RetrieveText = Callable[..., Awaitable[list[RetrievedChunk]]]
Today = Callable[[], str]


def _required_text(
    arguments: Mapping[str, Any],
    key: str,
    *,
    max_length: int,
) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} 必须是非空字符串")
    value = value.strip()
    if len(value) > max_length:
        raise ValueError(f"{key} 不能超过 {max_length} 字")
    return value


def _optional_int(
    arguments: Mapping[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = arguments.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} 必须是整数")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} 必须在 {minimum}..{maximum} 之间")
    return value


def _material_title(hit: RetrievedChunk) -> str:
    if hit.concept_id:
        return hit.concept_id
    name = hit.source_url.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return Path(name).stem or "材料"


def _material_sources(hits: Sequence[RetrievedChunk]) -> list[dict[str, Any]]:
    return [
        {
            "title": _material_title(hit),
            "url": hit.source_url,
            "excerpt": hit.source_excerpt,
            "kind": "material",
            "domain": "",
            "published_at": None,
            "retrieved_at": None,
            "chunk_id": hit.chunk_id,
        }
        for hit in hits
    ]


class SearchMaterialsTool:
    name = TOOL_SEARCH_MATERIALS

    def __init__(
        self,
        store: Store,
        embedder: Embedder,
        *,
        retrieve: RetrieveText = retrieve_text,
        min_cosine: float = 0.35,
        top_k: int = 3,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._retrieve = retrieve
        self._min_cosine = min_cosine
        self._top_k = top_k

    async def __call__(self, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            query = _required_text(arguments, "query", max_length=200)
            top_k = _optional_int(
                arguments,
                "top_k",
                default=self._top_k,
                minimum=1,
                maximum=5,
            )
        except ValueError as exc:
            return ToolResult.failure(
                self.name,
                code=CODE_INVALID_ARGUMENTS,
                message=str(exc),
                hint='示例：{"query": "Agent Loop", "top_k": 3}',
            )

        try:
            hits = await self._retrieve(
                self._store, self._embedder, query, top_k=top_k
            )
        except Exception as exc:
            return ToolResult.failure(
                self.name,
                code=CODE_PROVIDER_ERROR,
                message=f"本地检索失败：{exc}",
                hint="可以换更短的关键词再试，或直接用已有知识回答",
            )

        hits = list(hits)[:MAX_MATERIAL_RESULTS]
        return ToolResult.success(
            self.name,
            {
                "grounded": is_grounded(hits, min_cosine=self._min_cosine),
                "results": [
                    {
                        "index": index,
                        "title": _material_title(hit),
                        "excerpt": hit.source_excerpt,
                        "text": clip_text(hit.text, MAX_MATERIAL_CHARS),
                        "source_url": hit.source_url,
                        "concept_id": hit.concept_id,
                        "chunk_id": hit.chunk_id,
                        "parent_chunk_id": hit.parent_chunk_id,
                        "score": hit.score,
                    }
                    for index, hit in enumerate(hits, start=1)
                ],
                "sources": _material_sources(hits),
            },
        )


class SearchWebTool:
    name = TOOL_SEARCH_WEB

    def __init__(
        self,
        search: SearchProvider,
        *,
        max_results: int = 5,
        timeout_seconds: float = 8.0,
        today: Today | None = None,
    ) -> None:
        self._search = search
        self._max_results = max_results
        self._timeout = timeout_seconds
        self._today = today or (lambda: date.today().isoformat())

    async def __call__(self, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            query = _required_text(arguments, "query", max_length=200)
        except ValueError as exc:
            return ToolResult.failure(
                self.name,
                code=CODE_INVALID_ARGUMENTS,
                message=str(exc),
                hint='示例：{"query": "2026 年 agent 框架对比"}',
            )

        if getattr(self._search, "name", "") == "search-off":
            return ToolResult.failure(
                self.name,
                code=CODE_NOT_CONFIGURED,
                message="联网搜索未配置",
                retryable=False,
                hint="直接说明材料里没有，不要编造外部事实",
            )

        try:
            raw = await asyncio.wait_for(
                self._search.search(query, max_results=self._max_results),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            return ToolResult.failure(
                self.name,
                code=CODE_TIMEOUT,
                message=f"搜索超过 {self._timeout:g} 秒",
                hint="可以换更短的关键词再试，或直接用已有结果回答",
            )
        except Exception as exc:
            return ToolResult.failure(
                self.name,
                code=CODE_PROVIDER_ERROR,
                message=f"联网搜索失败：{exc}",
                hint="可以换更短的关键词再试，或直接用已有结果回答",
            )

        hits = filter_web_results(query, raw)[:MAX_WEB_RESULTS]
        retrieved_at = self._today()
        if not hits:
            return ToolResult.success(
                self.name,
                {
                    "status": "empty",
                    "trust": "untrusted",
                    "results": [],
                    "sources": [],
                },
            )

        return ToolResult.success(
            self.name,
            {
                "status": "ok",
                "trust": "untrusted",
                "results": [
                    {
                        "index": index,
                        "title": hit.title or domain_of(hit.url) or "网页",
                        "domain": domain_of(hit.url),
                        "url": hit.url,
                        "published_at": hit.published_at,
                        "retrieved_at": retrieved_at,
                        "snippet": clip_text(hit.content, MAX_WEB_CHARS),
                        "score": hit.score,
                    }
                    for index, hit in enumerate(hits, start=1)
                ],
                "sources": web_sources_payload(
                    hits, start_index=1, retrieved_at=retrieved_at
                ),
            },
        )


class ReadConceptTool:
    name = TOOL_READ_CONCEPT

    def __init__(self, concepts: Sequence[Concept]) -> None:
        self._lookup: dict[str, Concept] = {}
        for concept in concepts:
            for key in (concept.id, concept.name, *concept.aliases):
                normalized = key.strip().lower()
                if normalized:
                    self._lookup.setdefault(normalized, concept)

    async def __call__(self, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            query = _required_text(arguments, "concept", max_length=80)
        except ValueError as exc:
            return ToolResult.failure(
                self.name,
                code=CODE_INVALID_ARGUMENTS,
                message=str(exc),
                hint='示例：{"concept": "Agent Loop"}',
            )

        concept = self._lookup.get(query.lower())
        if concept is None:
            return ToolResult.failure(
                self.name,
                code=CODE_NOT_FOUND,
                message=f"没有找到概念：{query}",
                retryable=False,
                hint="可以改用 search_materials 检索材料",
            )

        return ToolResult.success(
            self.name,
            {
                "concept": {
                    "id": concept.id,
                    "name": concept.name,
                    "aliases": list(concept.aliases),
                    "plain_def": concept.plain_def,
                    "difficulty": concept.difficulty,
                    "prerequisites": list(concept.prerequisites),
                    "source_url": concept.source.url,
                    "source_excerpt": concept.source.excerpt,
                },
                "sources": [
                    {
                        "title": concept.name,
                        "url": concept.source.url,
                        "excerpt": concept.source.excerpt,
                        "kind": "material",
                        "domain": "",
                        "published_at": None,
                        "retrieved_at": None,
                        "chunk_id": f"concept:{concept.id}",
                    }
                ],
            },
        )


def build_agent_tools(
    *,
    store: Store,
    embedder: Embedder,
    search: SearchProvider,
    concepts: Sequence[Concept],
    min_cosine: float = 0.35,
    search_timeout_seconds: float = 8.0,
    today: Today | None = None,
) -> ToolRegistry:
    """组装三个只读工具；调用方只拿 registry，不单独持有适配器。"""
    return ToolRegistry(
        DEFAULT_TOOL_SPECS,
        {
            TOOL_SEARCH_MATERIALS: SearchMaterialsTool(
                store, embedder, min_cosine=min_cosine
            ),
            TOOL_SEARCH_WEB: SearchWebTool(
                search, timeout_seconds=search_timeout_seconds, today=today
            ),
            TOOL_READ_CONCEPT: ReadConceptTool(concepts),
        },
    )
