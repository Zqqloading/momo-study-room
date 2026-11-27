"""小米 MiMo 适配器：LLM 走 OpenAI 兼容 chat/completions，ASR 走 input_audio。

依据 2026-11-22 官方文档：
- LLM: ``POST https://api.xiaomimimo.com/v1/chat/completions``，模型
  ``mimo-v2.6-flash`` / ``mimo-v2.6-pro``，鉴权可用 ``api-key`` 或 Bearer。
- ASR: 同一个 ``/chat/completions``，模型 ``mimo-v2.5-asr``，音频以
  ``input_audio`` 的 data URI 传入，只支持 WAV/MP3。
"""

from __future__ import annotations

import base64
import time
from typing import Any, Sequence

import httpx

from core.ports import ASRRequest, ASRResult, ChatMessage

from ..config import Endpoint
from .base import HTTPAdapter, ProviderError, ensure_ok, join_url
from .openai_compat import OpenAICompatibleLLM

# 公开资料提到 10MB；文档没有明确写，先做前置保护，实测后校准。
MAX_ASR_AUDIO_BYTES = 10 * 1024 * 1024

_WAV_MIMES = {"audio/wav", "audio/x-wav", "audio/wave"}
_MP3_MIMES = {"audio/mpeg", "audio/mp3"}


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class MiMoLLM(OpenAICompatibleLLM):
    """MiMo 的 chat 接口是 OpenAI 兼容的，只差鉴权头和 temperature。

    MiMo 在 thinking 模式下不接受自定义 temperature/top_p，所以默认不发送；
    需要时用 ``LLM_SEND_TEMPERATURE=1`` 打开。
    """

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float,
        send_temperature: bool = False,
        auth_header: str = "api-key",
    ) -> None:
        super().__init__(endpoint, timeout=timeout, auth_header=auth_header)
        self.name = "mimo-llm"
        self._send_temperature = send_temperature

    def _payload(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float,
        max_tokens: int | None,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload = super()._payload(
            messages, temperature=temperature, max_tokens=max_tokens, stream=stream
        )
        if not self._send_temperature:
            payload.pop("temperature", None)
        return payload


class MiMoASR(HTTPAdapter):
    name = "mimo-asr"

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float,
        language: str = "zh",
        auth_header: str = "api-key",
    ) -> None:
        super().__init__(endpoint, timeout=timeout, auth_header=auth_header)
        self.model = endpoint.model or "mimo-v2.5-asr"
        self.language = language

    async def transcribe(self, request: ASRRequest) -> ASRResult:
        if not request.audio:
            return ASRResult(text="", confidence=None)

        mime = request.mime.lower()
        if mime in _WAV_MIMES:
            audio_format, data_mime = "wav", "audio/wav"
        elif mime in _MP3_MIMES:
            audio_format, data_mime = "mp3", "audio/mpeg"
        else:
            raise ProviderError(f"MiMo ASR 只接受 WAV 或 MP3，收到 {request.mime!r}")

        if len(request.audio) > MAX_ASR_AUDIO_BYTES:
            raise ProviderError("MiMo ASR 单次音频超过 10MB，请缩短录音或先压缩")

        encoded = base64.b64encode(request.audio).decode("ascii")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:{data_mime};base64,{encoded}",
                                "format": audio_format,
                            },
                        }
                    ],
                }
            ],
            "asr_options": {"language": request.language or self.language},
        }

        started = time.perf_counter()
        try:
            response = await self._client.post(
                join_url(self.base_url, "/chat/completions"),
                json=payload,
                headers=self.headers(),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label} 连接失败：{exc}") from exc
        ensure_ok(response, self.label)

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.label} 响应形状不对：{data}") from exc

        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if not isinstance(content, str):
            raise ProviderError(f"{self.label} 响应里没有转写文本：{data}")

        return ASRResult(
            text=content.strip(),
            confidence=None,
            latency_ms=_elapsed_ms(started),
        )
