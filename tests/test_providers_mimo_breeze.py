from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from bff.config import Endpoint
from bff.providers.base import ProviderError, ProviderNotConfigured
from bff.providers.breeze import BreezeTTS
from bff.providers.mimo import MiMoASR
from core.ports import ASRRequest


def test_mimo_asr_builds_input_audio_request() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": " 你好 "}}]})

    async def scenario():
        adapter = MiMoASR(
            Endpoint(
                label="MiMo ASR",
                base_url="https://api.xiaomimimo.com/v1",
                api_key="mimo-key",
                model="mimo-v2.5-asr",
            ),
            timeout=5,
        )
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await adapter.transcribe(
                ASRRequest(audio=b"RIFF", mime="audio/wav", language="zh")
            )
        finally:
            await adapter.aclose()

    result = asyncio.run(scenario())
    assert result.text == "你好"
    assert str(seen["url"]).endswith("/chat/completions")
    assert seen["api_key"] == "mimo-key"

    body = seen["body"]
    assert body["model"] == "mimo-v2.5-asr"
    part = body["messages"][0]["content"][0]
    assert part["type"] == "input_audio"
    assert part["input_audio"]["format"] == "wav"
    assert part["input_audio"]["data"].startswith("data:audio/wav;base64,")
    assert body["asr_options"]["language"] == "zh"


def test_mimo_asr_rejects_non_wav_mp3() -> None:
    adapter = MiMoASR(
        Endpoint(label="MiMo ASR", base_url="https://api.xiaomimimo.com/v1"),
        timeout=5,
    )

    async def scenario():
        try:
            await adapter.transcribe(ASRRequest(audio=b"x", mime="audio/webm"))
        finally:
            await adapter.aclose()

    with pytest.raises(ProviderError, match="WAV 或 MP3"):
        asyncio.run(scenario())


def test_breeze_tts_posts_to_voice_endpoint() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["output_format"] = request.url.params.get("output_format")
        seen["api_key"] = request.headers.get("xi-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"ID3", headers={"content-type": "audio/mpeg"})

    async def scenario():
        adapter = BreezeTTS(
            Endpoint(
                label="Breeze TTS",
                base_url="https://api.breeze.blue",
                api_key="brz-test",
                model="breeze-tts-2",
            ),
            timeout=5,
            voice="voc_test",
            language="zh",
            output_format="mp3_24000_128",
        )
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await adapter.synthesize("你好")
        finally:
            await adapter.aclose()

    result = asyncio.run(scenario())
    assert result.audio == b"ID3"
    assert result.mime == "audio/mpeg"
    assert seen["path"] == "/v1/text-to-speech/voc_test"
    assert seen["output_format"] == "mp3_24000_128"
    assert seen["api_key"] == "brz-test"
    assert seen["body"] == {
        "text": "你好",
        "model_id": "breeze-tts-2",
        "language_code": "zh",
    }


def test_breeze_tts_requires_voice() -> None:
    adapter = BreezeTTS(
        Endpoint(label="Breeze TTS", base_url="https://api.breeze.blue", api_key="brz-test"),
        timeout=5,
        voice="",
    )

    async def scenario():
        try:
            await adapter.synthesize("你好")
        finally:
            await adapter.aclose()

    with pytest.raises(ProviderNotConfigured, match="TTS_VOICE"):
        asyncio.run(scenario())
