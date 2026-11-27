"""OpenAI 兼容 /embeddings 适配器（阿里 DashScope text-embedding-v4）。"""

from __future__ import annotations

from typing import Sequence

import httpx

from ..config import Endpoint
from .base import HTTPAdapter, ProviderError, ensure_ok, join_url


class OpenAICompatibleEmbedder(HTTPAdapter):
    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float,
        dim: int,
        auth_header: str = "authorization",
    ) -> None:
        super().__init__(endpoint, timeout=timeout, auth_header=auth_header)
        self.name = "openai-compatible-embedding"
        self.model = endpoint.model
        self.dim = dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {
            "model": self.model,
            "input": list(texts),
            "dimensions": self.dim,
        }
        try:
            response = await self._client.post(
                join_url(self.base_url, "/embeddings"),
                json=payload,
                headers=self.headers(),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label} 连接失败：{exc}") from exc
        ensure_ok(response, self.label)

        data = response.json()
        try:
            items = sorted(data["data"], key=lambda item: item.get("index", 0))
            vectors = [[float(value) for value in item["embedding"]] for item in items]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"{self.label} 响应形状不对：{data}") from exc

        if len(vectors) != len(texts) or any(len(vector) != self.dim for vector in vectors):
            raise ProviderError(
                f"{self.label} 返回 {len(vectors)} 条、维度不符（期望 {self.dim}）"
            )
        return vectors
