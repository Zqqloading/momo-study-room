"""Breeze Blue TTS 适配器。

依据 2026-11-22 官方文档：
- ``POST https://api.breeze.blue/v1/text-to-speech/{voice_id}?output_format=mp3_24000_128``
- 鉴权头：``xi-api-key: brz_...``
- body：``{"text": ..., "model_id": "breeze-tts-2", "language_code": "zh"}``
- 流式：``/v1/text-to-speech/{voice_id}/stream``，按 chunk 返回音频。
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator

import httpx

from core.ports import TTSResult

from ..config import Endpoint
from .base import HTTPAdapter, ProviderError, ProviderNotConfigured, ensure_ok, join_url


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class BreezeTTS(HTTPAdapter):
    name = "breeze-tts"
    supports_streaming = True
    stream_mime = "audio/mpeg"

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float,
        voice: str,
        model: str = "breeze-tts-2",
        language: str = "zh",
        output_format: str = "mp3_24000_128",
    ) -> None:
        super().__init__(endpoint, timeout=timeout, auth_header="xi-api-key")
        self.model = endpoint.model or model
        self.voice = voice
        self.language = language
        self.output_format = output_format

    def _url(self, voice: str | None, *, stream: bool) -> str:
        voice_id = (voice or self.voice).strip()
        if not voice_id:
            raise ProviderNotConfigured(
                "TTS_VOICE 未配置：Breeze 需要 voice_id（形如 voc_...），从控制台复制"
            )
        suffix = "/stream" if stream else ""
        return join_url(self.base_url, f"/v1/text-to-speech/{voice_id}{suffix}")

    def _payload(self, text: str) -> dict[str, Any]:
        return {
            "text": text,
            "model_id": self.model,
            "language_code": self.language,
        }

    def _stream_format(self) -> str:
        # /stream 只接受 mp3、pcm、wav；不能带 24000_128 这类后缀。
        for prefix in ("mp3", "wav", "pcm"):
            if self.output_format.startswith(prefix):
                return prefix
        return "mp3"

    def _mime(self, content_type: str | None) -> str:
        value = (content_type or "").split(";")[0].strip().lower()
        if value.startswith("audio/"):
            return value
        if self.output_format.startswith("wav"):
            return "audio/wav"
        if self.output_format.startswith("pcm"):
            return "audio/pcm"
        return "audio/mpeg"

    async def synthesize(self, text: str, *, voice: str | None = None) -> TTSResult:
        if not text.strip():
            return TTSResult(audio=b"", mime="")

        url = self._url(voice, stream=False)
        started = time.perf_counter()
        try:
            response = await self._client.post(
                url,
                params={"output_format": self.output_format},
                json=self._payload(text),
                headers=self.headers(accept="audio/*"),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label} 连接失败：{exc}") from exc
        ensure_ok(response, self.label)

        return TTSResult(
            audio=response.content,
            mime=self._mime(response.headers.get("content-type")),
            latency_ms=_elapsed_ms(started),
        )

    async def stream(
        self, text: str, *, voice: str | None = None
    ) -> AsyncIterator[bytes]:
        if not text.strip():
            return
        url = self._url(voice, stream=True)
        try:
            async with self._client.stream(
                "POST",
                url,
                params={"output_format": self._stream_format()},
                json=self._payload(text),
                headers=self.headers(accept="audio/*"),
            ) as response:
                if not response.is_success:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise ProviderError(
                        f"{self.label} 返回 HTTP {response.status_code}：{body[:300]}"
                    )
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label} 连接失败：{exc}") from exc
