from __future__ import annotations

import asyncio
import json
import struct

import httpx
import pytest

from bff.config import Endpoint
from bff.providers.base import ProviderError
from bff.providers.deepseek_tts import DeepSeekTTS


def _placeholder_wav() -> bytes:
    return (
        b"RIFF"
        + struct.pack("<I", 0xFFFFFFFF)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + b"\x01\x00\x01\x00"
        + struct.pack("<I", 24_000)
        + struct.pack("<I", 48_000)
        + b"\x02\x00\x10\x00"
        + b"data"
        + struct.pack("<I", 0xFFFFFFFF)
        + b"\x00\x01" * 8
    )


def test_deepseek_tts_posts_and_seals_wav() -> None:
    seen: dict[str, object] = {}
    payload = _placeholder_wav()

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["api_key"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, content=payload, headers={"content-type": "audio/wav"}
        )

    async def scenario():
        adapter = DeepSeekTTS(
            Endpoint(
                label="DeepSeek TTS",
                base_url="https://api.deepseek.com",
                api_key="sk-test",
            ),
            timeout=5,
            voice="stella",
        )
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await adapter.synthesize("你好")
        finally:
            await adapter.aclose()

    result = asyncio.run(scenario())
    assert seen["path"] == "/v1/tools/tts"
    assert seen["api_key"] == "Bearer sk-test"
    assert seen["body"] == {"text": "你好", "format": "wav", "voice_id": "stella"}
    assert result.mime == "audio/wav"
    assert struct.unpack_from("<I", result.audio, 4)[0] == len(result.audio) - 8
    data_at = result.audio.find(b"data")
    assert struct.unpack_from("<I", result.audio, data_at + 4)[0] == (
        len(result.audio) - data_at - 8
    )


def test_deepseek_tts_error_surfaces_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            json={"code": "BILLING_INSUFFICIENT_CREDITS", "detail": "Insufficient credits."},
        )

    async def scenario():
        adapter = DeepSeekTTS(
            Endpoint(
                label="DeepSeek TTS",
                base_url="https://api.deepseek.com",
                api_key="sk-test",
            ),
            timeout=5,
        )
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await adapter.synthesize("你好")
        finally:
            await adapter.aclose()

    with pytest.raises(ProviderError, match="402"):
        asyncio.run(scenario())
