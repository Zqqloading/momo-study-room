"""Tavily 搜索适配器（OpenAI/JSON 风格的 POST /search）。"""

from __future__ import annotations

from core.ports import SearchHit

from ..config import Endpoint
from .base import HTTPAdapter, ProviderError, ensure_ok, join_url


class TavilySearch(HTTPAdapter):
    name = "tavily"

    def __init__(self, endpoint: Endpoint, *, timeout: float = 8.0) -> None:
        super().__init__(endpoint, timeout=timeout, auth_header="authorization")

    async def search(
        self, query: str, *, max_results: int = 5
    ) -> list[SearchHit]:
        response = await self._client.post(
            join_url(self.base_url, "/search"),
            json={
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": False,
            },
            headers={**self.headers(), "Content-Type": "application/json"},
        )
        ensure_ok(response, self.label)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(f"{self.label} 返回的不是 JSON") from exc
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return []

        hits: list[SearchHit] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            score = item.get("score")
            try:
                normalized_score = float(score) if score is not None else 0.0
            except (TypeError, ValueError):
                normalized_score = 0.0
            published = item.get("published_date")
            hits.append(
                SearchHit(
                    title=str(item.get("title") or url).strip(),
                    url=url,
                    content=str(item.get("content") or "").strip(),
                    score=normalized_score,
                    published_at=str(published).strip() if published else None,
                )
            )
        return hits
