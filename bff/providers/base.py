"""适配器共用：错误类型与 HTTP 基类。"""

from __future__ import annotations

import httpx

from ..config import Endpoint


class ProviderError(RuntimeError):
    """外部服务调用失败。BFF 捕获后降级（只显示文字）。"""


class ProviderNotConfigured(ProviderError):
    """接口信息还没拿到，或配置缺失。"""


def http_error(response: httpx.Response, label: str) -> ProviderError:
    return ProviderError(f"{label} 返回 HTTP {response.status_code}：{response.text[:300]}")


def ensure_ok(response: httpx.Response, label: str) -> None:
    if not response.is_success:
        raise http_error(response, label)


def join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


class HTTPAdapter:
    """持有一个 httpx 客户端；鉴权头可按供应商切换。

    ``auth_header`` 取 ``authorization``（Bearer）或 ``api-key`` /
    ``xi-api-key`` 这类直接放密钥的请求头。
    """

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float,
        auth_header: str = "authorization",
    ) -> None:
        self.label = endpoint.label
        self.base_url = endpoint.base_url.rstrip("/")
        self._api_key = endpoint.api_key
        self._auth_header = auth_header
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0))

    def headers(self, accept: str = "application/json") -> dict[str, str]:
        headers = {"Accept": accept}
        if self._api_key:
            if self._auth_header.lower() == "authorization":
                headers["Authorization"] = f"Bearer {self._api_key}"
            else:
                headers[self._auth_header] = self._api_key
        return headers

    async def aclose(self) -> None:
        await self._client.aclose()
