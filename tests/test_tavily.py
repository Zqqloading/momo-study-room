from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from bff.config import Endpoint
from bff.providers.base import ProviderError
from bff.providers.tavily import TavilySearch


def make_adapter(handler) -> TavilySearch:
    adapter = TavilySearch(
        Endpoint(label="Tavily", base_url="https://api.tavily.com", api_key="tvly-key"),
        timeout=5,
    )
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


def test_tavily_search_builds_request_and_parses_results() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Agent 教程",
                        "url": "https://example.com/agent",
                        "content": "Agent 会观察、决策、行动。" * 10,
                        "score": 0.87,
                        "published_date": "2026-11-20",
                    }
                ]
            },
        )

    async def scenario():
        adapter = make_adapter(handler)
        try:
            return await adapter.search("最新 agent", max_results=5)
        finally:
            await adapter.aclose()

    hits = asyncio.run(scenario())
    assert str(seen["url"]).endswith("/search")
    assert seen["auth"] == "Bearer tvly-key"
    body = seen["body"]
    assert body["query"] == "最新 agent"
    assert body["search_depth"] == "basic"
    assert body["max_results"] == 5
    assert body["include_answer"] is False
    assert len(hits) == 1
    assert hits[0].title == "Agent 教程"
    assert hits[0].score == pytest.approx(0.87)
    assert hits[0].published_at == "2026-11-20"


def test_tavily_search_reports_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    async def scenario():
        adapter = make_adapter(handler)
        try:
            await adapter.search("agent")
        finally:
            await adapter.aclose()

    with pytest.raises(ProviderError, match="429"):
        asyncio.run(scenario())


def test_tavily_search_handles_missing_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async def scenario():
        adapter = make_adapter(handler)
        try:
            return await adapter.search("agent")
        finally:
            await adapter.aclose()

    assert asyncio.run(scenario()) == []
