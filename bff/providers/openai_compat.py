"""OpenAI 兼容形状的适配器。

DeepSeek Flash 与通用 OpenAI 兼容服务走这一套。MiMo ASR 与 Breeze TTS
有各自的真实形状，分别在 ``mimo.py`` 与 ``breeze.py``。
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Sequence

import httpx

from core.ports import ASRRequest, ASRResult, ChatMessage, TTSResult

from ..config import Endpoint
from .base import HTTPAdapter, ProviderError, ProviderNotConfigured, ensure_ok, join_url

_EXTENSIONS = {
    "audio/wav": "audio.wav",
    "audio/x-wav": "audio.wav",
    "audio/webm": "audio.webm",
    "audio/ogg": "audio.ogg",
    "audio/mpeg": "audio.mp3",
    "audio/mp4": "audio.m4a",
}


def _endpoint(base_url: str, path: str) -> str:
    return join_url(base_url, path)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class OpenAICompatibleLLM(HTTPAdapter):
    supports_streaming = True

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float,
        auth_header: str = "authorization",
    ) -> None:
        super().__init__(endpoint, timeout=timeout, auth_header=auth_header)
        self.name = "openai-compatible-llm"
        self.model = endpoint.model

    def _payload(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float,
        max_tokens: int | None,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if stream:
            payload["stream"] = True
        return payload

    @staticmethod
    def _content(data: dict[str, Any]) -> str:
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"响应形状不对：{data}") from exc

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        try:
            response = await self._client.post(
                _endpoint(self.base_url, "/chat/completions"),
                json=self._payload(messages, temperature=temperature, max_tokens=max_tokens),
                headers=self.headers(),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label} 连接失败：{exc}") from exc
        ensure_ok(response, self.label)
        return self._content(response.json())

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        payload = self._payload(
            messages, temperature=temperature, max_tokens=max_tokens, stream=True
        )
        try:
            async with self._client.stream(
                "POST",
                _endpoint(self.base_url, "/chat/completions"),
                json=payload,
                headers=self.headers(),
            ) as response:
                if not response.is_success:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise ProviderError(
                        f"{self.label} 返回 HTTP {response.status_code}：{body[:300]}"
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        return
                    if not chunk:
                        continue
                    try:
                        event = json.loads(chunk)
                        piece = (event["choices"][0].get("delta") or {}).get("content")
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        continue
                    if piece:
                        yield piece
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label} 连接失败：{exc}") from exc


class OpenAICompatibleScorer(HTTPAdapter):
    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float,
        json_mode: bool = False,
        auth_header: str = "authorization",
    ) -> None:
        super().__init__(endpoint, timeout=timeout, auth_header=auth_header)
        self.name = "openai-compatible-scorer"
        self.model = endpoint.model
        self.json_mode = json_mode

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            response = await self._client.post(
                _endpoint(self.base_url, "/chat/completions"),
                json=payload,
                headers=self.headers(),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label} 连接失败：{exc}") from exc
        ensure_ok(response, self.label)

        data = response.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.label} 响应形状不对：{data}") from exc


class OpenAICompatibleASR(HTTPAdapter):
    """临时形状：``POST {base_url}/audio/transcriptions``（multipart）。"""

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float,
        language: str = "zh",
        auth_header: str = "authorization",
    ) -> None:
        super().__init__(endpoint, timeout=timeout, auth_header=auth_header)
        self.name = "openai-compatible-asr"
        self.model = endpoint.model
        self.language = language

    async def transcribe(self, request: ASRRequest) -> ASRResult:
        if not request.audio:
            return ASRResult(text="", confidence=None)

        filename = _EXTENSIONS.get(request.mime, "audio.bin")
        data: dict[str, str] = {}
        if self.model:
            data["model"] = self.model
        if request.language:
            data["language"] = request.language
        if request.hotwords:
            data["prompt"] = "、".join(request.hotwords)

        started = time.perf_counter()
        try:
            response = await self._client.post(
                _endpoint(self.base_url, "/audio/transcriptions"),
                files={"file": (filename, request.audio, request.mime)},
                data=data,
                headers=self.headers(),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label} 连接失败：{exc}") from exc
        ensure_ok(response, self.label)

        payload = response.json()
        text = payload.get("text")
        if not isinstance(text, str):
            raise ProviderError(f"{self.label} 响应里没有 text：{payload}")
        confidence = payload.get("confidence")
        return ASRResult(
            text=text.strip(),
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
            latency_ms=_elapsed_ms(started),
        )


class OpenAICompatibleTTS(HTTPAdapter):
    """临时形状：``POST {base_url}/audio/speech``，返回二进制音频。"""

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float,
        voice: str,
        auth_header: str = "authorization",
    ) -> None:
        super().__init__(endpoint, timeout=timeout, auth_header=auth_header)
        self.name = "openai-compatible-tts"
        self.model = endpoint.model
        self.voice = voice
        # 流式尚未实测；breezeblue 不支持时冻结规格把短答目标放宽到 4 秒。
        self.supports_streaming = False

    async def synthesize(self, text: str, *, voice: str | None = None) -> TTSResult:
        if not text.strip():
            return TTSResult(audio=b"", mime="")

        payload: dict[str, Any] = {"input": text, "voice": voice or self.voice}
        if self.model:
            payload["model"] = self.model

        started = time.perf_counter()
        try:
            response = await self._client.post(
                _endpoint(self.base_url, "/audio/speech"),
                json=payload,
                headers=self.headers(accept="audio/*"),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label} 连接失败：{exc}") from exc
        ensure_ok(response, self.label)

        mime = response.headers.get("content-type", "audio/mpeg").split(";")[0].strip()
        return TTSResult(
            audio=response.content,
            mime=mime or "audio/mpeg",
            latency_ms=_elapsed_ms(started),
        )


def require_base_url(endpoint: Endpoint) -> Endpoint:
    if not endpoint.configured:
        raise ProviderNotConfigured(
            f"{endpoint.label} 未配置：缺 base_url（见 .env.example 与待定区）"
        )
    return endpoint
