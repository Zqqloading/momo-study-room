from __future__ import annotations

import asyncio

from bff.agent_tools import ReadConceptTool, SearchMaterialsTool, SearchWebTool
from core.agent_tools import (
    CODE_INVALID_ARGUMENTS,
    CODE_NOT_CONFIGURED,
    CODE_NOT_FOUND,
    CODE_PROVIDER_ERROR,
    CODE_TIMEOUT,
)
from core.concepts import load_concepts
from core.ports import SearchHit
from core.retrieval import RetrievedChunk
from tests.support import CONCEPTS_PATH, make_store


def _chunk(**overrides) -> RetrievedChunk:
    values = {
        "concept_id": "agent-loop",
        "text": "父块全文",
        "source_excerpt": "摘录",
        "source_url": "fixture://agent-loop",
        "score": 0.9,
        "chunk_id": "chunk-1",
        "parent_chunk_id": "parent-1",
        "fts_hit": True,
    }
    values.update(overrides)
    return RetrievedChunk(**values)


def _counts(store) -> tuple[int, ...]:
    tables = ("materials", "concept_sources", "question_bank", "session_questions")
    return tuple(
        int(store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    )


def test_search_materials_success() -> None:
    store = make_store()
    before = _counts(store)

    async def retrieve(store, embedder, query, *, top_k=3):
        assert query == "Agent Loop"
        assert top_k == 2
        return [
            _chunk(text="a" * 1300),
            _chunk(chunk_id="chunk-2", source_url="fixture://other", fts_hit=False),
        ]

    tool = SearchMaterialsTool(store, object(), retrieve=retrieve)
    result = asyncio.run(tool({"query": "Agent Loop", "top_k": 2}))

    assert result.ok is True
    assert result.data is not None
    assert result.data["grounded"] is True
    assert len(result.data["results"]) == 2
    assert len(result.data["results"][0]["text"]) == 1201  # 1200 + 省略号
    assert result.data["sources"][0]["chunk_id"] == "chunk-1"
    assert _counts(store) == before


def test_search_materials_empty_result() -> None:
    store = make_store()

    async def retrieve(store, embedder, query, *, top_k=3):
        return []

    tool = SearchMaterialsTool(store, object(), retrieve=retrieve)
    result = asyncio.run(tool({"query": "不存在"}))
    assert result.ok is True
    assert result.data == {"grounded": False, "results": [], "sources": []}


def test_search_materials_provider_error() -> None:
    store = make_store()

    async def retrieve(store, embedder, query, *, top_k=3):
        raise RuntimeError("embedding down")

    tool = SearchMaterialsTool(store, object(), retrieve=retrieve)
    result = asyncio.run(tool({"query": "x"}))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_PROVIDER_ERROR


def test_search_materials_invalid_arguments() -> None:
    store = make_store()

    async def retrieve(store, embedder, query, *, top_k=3):  # pragma: no cover
        raise AssertionError("should not run")

    tool = SearchMaterialsTool(store, object(), retrieve=retrieve)
    for arguments in ({}, {"query": ""}, {"query": "x", "top_k": 9}):
        result = asyncio.run(tool(arguments))
        assert result.ok is False
        assert result.error is not None
        assert result.error.code == CODE_INVALID_ARGUMENTS


def test_search_materials_caps_results() -> None:
    store = make_store()

    async def retrieve(store, embedder, query, *, top_k=3):
        return [
            _chunk(chunk_id=f"chunk-{index}", source_url=f"fixture://{index}")
            for index in range(5)
        ]

    tool = SearchMaterialsTool(store, object(), retrieve=retrieve)
    result = asyncio.run(tool({"query": "agent", "top_k": 5}))
    assert result.ok is True
    assert result.data is not None
    assert len(result.data["results"]) == 3
    assert len(result.data["sources"]) == 3


class FakeSearch:
    name = "fake-search"

    def __init__(
        self,
        hits: list[SearchHit] | None = None,
        *,
        error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.hits = list(hits or [])
        self.error = error
        self.delay = delay
        self.calls = 0

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.hits


class OffSearch:
    name = "search-off"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        return []


def _hit(url: str = "https://example.com/a", title: str = "A") -> SearchHit:
    return SearchHit(
        title=title,
        url=url,
        content="agent " + "这是足够长的外部内容。" * 8,
        score=0.9,
        published_at="2026-11-20",
    )


def test_search_web_success() -> None:
    store = make_store()
    before = _counts(store)
    search = FakeSearch([_hit(), _hit("https://example.org/b", "B")])
    tool = SearchWebTool(search, today=lambda: "2026-11-25")

    result = asyncio.run(tool({"query": "agent"}))
    assert result.ok is True
    assert result.data is not None
    assert result.data["status"] == "ok"
    assert result.data["trust"] == "untrusted"
    assert len(result.data["results"]) == 2
    assert len(result.data["sources"]) == 2
    assert result.data["sources"][0]["retrieved_at"] == "2026-11-25"
    assert _counts(store) == before


def test_search_web_empty_result() -> None:
    store = make_store()
    tool = SearchWebTool(FakeSearch([]), today=lambda: "2026-11-25")
    result = asyncio.run(tool({"query": "agent"}))
    assert result.ok is True
    assert result.data == {
        "status": "empty",
        "trust": "untrusted",
        "results": [],
        "sources": [],
    }


def test_search_web_not_configured() -> None:
    store = make_store()
    tool = SearchWebTool(OffSearch())
    result = asyncio.run(tool({"query": "agent"}))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_NOT_CONFIGURED


def test_search_web_timeout() -> None:
    store = make_store()
    tool = SearchWebTool(FakeSearch([_hit()], delay=0.05), timeout_seconds=0.01)
    result = asyncio.run(tool({"query": "agent"}))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_TIMEOUT


def test_search_web_provider_error() -> None:
    store = make_store()
    tool = SearchWebTool(FakeSearch(error=RuntimeError("tavily down")))
    result = asyncio.run(tool({"query": "agent"}))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_PROVIDER_ERROR


def test_search_web_invalid_query() -> None:
    store = make_store()
    tool = SearchWebTool(FakeSearch([]))
    result = asyncio.run(tool({"query": "   "}))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_INVALID_ARGUMENTS


def test_search_web_caps_results() -> None:
    store = make_store()
    hits = [_hit(f"https://example.com/{index}", f"T{index}") for index in range(5)]
    tool = SearchWebTool(FakeSearch(hits), today=lambda: "2026-11-25")
    result = asyncio.run(tool({"query": "agent"}))
    assert result.ok is True
    assert result.data is not None
    assert len(result.data["results"]) == 3
    assert len(result.data["sources"]) == 3


def test_read_concept_hit_by_id_alias_and_name() -> None:
    tool = ReadConceptTool(load_concepts(CONCEPTS_PATH))
    for query, expected in (
        ("agent-loop", "agent-loop"),
        ("agent loop", "agent-loop"),
        ("工具调用", "tool-use"),
        ("记忆", "memory"),
    ):
        result = asyncio.run(tool({"concept": query}))
        assert result.ok is True
        assert result.data is not None
        assert result.data["concept"]["id"] == expected
        assert result.data["sources"][0]["chunk_id"] == f"concept:{expected}"


def test_read_concept_not_found() -> None:
    tool = ReadConceptTool(load_concepts(CONCEPTS_PATH))
    result = asyncio.run(tool({"concept": "不存在的概念"}))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_NOT_FOUND


def test_read_concept_invalid_arguments() -> None:
    tool = ReadConceptTool(load_concepts(CONCEPTS_PATH))
    result = asyncio.run(tool({"concept": "   "}))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_INVALID_ARGUMENTS
