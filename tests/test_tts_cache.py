from __future__ import annotations

import asyncio

from core.ports import TTSResult
from core.tts_cache import TTSCache


class CountingTTS:
    supports_streaming = False

    def __init__(self) -> None:
        self.calls = 0
        self.voices: list[str | None] = []

    async def synthesize(self, text: str, *, voice: str | None = None) -> TTSResult:
        self.calls += 1
        self.voices.append(voice)
        return TTSResult(audio=f"audio:{text}".encode(), mime="audio/wav", latency_ms=1)


def make_cache(tmp_path, *, voice="v1", model="m1", output_format="wav"):
    provider = CountingTTS()
    cache = TTSCache(
        provider, tmp_path / "cache", voice=voice, model=model, output_format=output_format
    )
    return provider, cache


def test_key_changes_with_text_voice_model_and_format(tmp_path) -> None:
    _, cache = make_cache(tmp_path)
    base = cache.key("题目")
    assert base != cache.key("另一题")

    _, other_voice = make_cache(tmp_path, voice="v2")
    _, other_model = make_cache(tmp_path, model="m2")
    _, other_format = make_cache(tmp_path, output_format="mp3")
    assert base != other_voice.key("题目")
    assert base != other_model.key("题目")
    assert base != other_format.key("题目")


def test_cache_hit_skips_provider(tmp_path) -> None:
    provider, cache = make_cache(tmp_path)
    first = asyncio.run(cache.get_or_synthesize("第一题"))
    second = asyncio.run(cache.get_or_synthesize("第一题"))

    assert first == second
    assert provider.calls == 1
    assert provider.voices == ["v1"]


def test_cache_miss_writes_files(tmp_path) -> None:
    _, cache = make_cache(tmp_path)
    audio, mime = asyncio.run(cache.get_or_synthesize("第一题"))
    assert audio == "audio:第一题".encode()
    assert mime == "audio/wav"

    cache_dir = tmp_path / "cache"
    assert len(list(cache_dir.glob("*.bin"))) == 1
    mime_files = list(cache_dir.glob("*.mime"))
    assert len(mime_files) == 1
    assert mime_files[0].read_text(encoding="utf-8") == "audio/wav"


def test_empty_audio_is_not_cached(tmp_path) -> None:
    class EmptyTTS:
        supports_streaming = False

        async def synthesize(self, text: str, *, voice: str | None = None) -> TTSResult:
            return TTSResult(audio=b"", mime="")

    cache = TTSCache(EmptyTTS(), tmp_path / "cache")
    audio, mime = asyncio.run(cache.get_or_synthesize("空"))
    assert audio == b""
    assert mime == ""
    assert not (tmp_path / "cache").exists()
