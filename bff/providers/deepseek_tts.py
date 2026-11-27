"""DeepSeek TTS 适配器。

依据 2026-11-25 官方文档：
- ``POST {base_url}/v1/tools/tts``
- 鉴权头：``Authorization: Bearer``（与 chat / 评分共用同一把 key）
- body：``{"text": ..., "voice_id": "stella"|"tide", "format": "wav"}``
- 返回流式 WAV；RIFF/data 长度字段是 ``0xFFFFFFFF`` 占位，落盘前回填真实长度。
"""

from __future__ import annotations

import struct
import time

import httpx

from core.ports import TTSResult

from ..config import Endpoint
from .base import HTTPAdapter, ProviderError, ensure_ok, join_url


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _seal_wav(audio: bytes) -> bytes:
    """回填流式 WAV 的占位长度；带占位值的头会让播放器时长显示异常。"""
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return audio
    index = audio.find(b"data")
    if index < 0 or index + 8 > len(audio):
        return audio
    buf = bytearray(audio)
    if struct.unpack_from("<I", buf, 4)[0] in (0, 0xFFFFFFFF):
        struct.pack_into("<I", buf, 4, len(buf) - 8)
    if struct.unpack_from("<I", buf, index + 4)[0] in (0, 0xFFFFFFFF):
        struct.pack_into("<I", buf, index + 4, len(buf) - index - 8)
    return bytes(buf)


class DeepSeekTTS(HTTPAdapter):
    name = "deepseek-tts"
    supports_streaming = False

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float,
        voice: str = "stella",
        audio_format: str = "wav",
    ) -> None:
        super().__init__(endpoint, timeout=timeout)
        self.voice = voice
        self.audio_format = audio_format

    async def synthesize(self, text: str, *, voice: str | None = None) -> TTSResult:
        if not text.strip():
            return TTSResult(audio=b"", mime="")

        payload: dict[str, str] = {"text": text, "format": self.audio_format}
        voice_id = (voice or self.voice).strip()
        if voice_id:
            payload["voice_id"] = voice_id

        started = time.perf_counter()
        try:
            response = await self._client.post(
                join_url(self.base_url, "/v1/tools/tts"),
                json=payload,
                headers=self.headers(accept="audio/*"),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label} 连接失败：{exc}") from exc
        ensure_ok(response, self.label)

        mime = (response.headers.get("content-type") or "").split(";")[0].strip()
        return TTSResult(
            audio=_seal_wav(response.content),
            mime=mime or "audio/wav",
            latency_ms=_elapsed_ms(started),
        )
