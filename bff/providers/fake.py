"""离线假实现：没有外部 API 时也能跑通整条链路。

用途只有两个：d0 联调、单元测试。健康检查与界面会明确显示"离线假模式"，
不会把假结果当成实测值。真实接口到手后把 PROVIDER_MODE 改回 auto/real 即可。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import math
import re
import time
import wave
from array import array
from typing import AsyncIterator, Sequence

from core.ports import (
    ASRRequest,
    ASRResult,
    ChatMessage,
    SearchHit,
    TTSResult,
)

FAKE_TRANSCRIPT = "agent 就是能自己决定下一步的程序，workflow 是人把步骤写死的。"

FAKE_SEARCH_CONTENT = (
    "这是一条离线假搜索结果，仅用于测试自由对话的联网兜底路径，不代表真实网页内容。"
    "它包含足够长的正文，以便通过 content 预过滤；同时包含 agent、workflow 与学习这些词，"
    "方便测试词面重叠。如果你在真实环境看到这条来源，说明搜索仍然处于 fake 模式。"
)

FAKE_SEARCH_HITS = (
    SearchHit(
        title="离线假搜索结果",
        url="https://example.com/fake-agent",
        content=FAKE_SEARCH_CONTENT,
        score=0.9,
        published_at="2026-11-20",
    ),
)

FAKE_ANSWER = (
    "你抓住了关键：agent 会自己决定下一步，workflow 的步骤是人写死的。"
    "再具体一点：agent 每次行动前会看当前情况选下一步。"
    "那你用自己的话说说，什么情况下你会宁愿用 workflow？"
)


def synthesize_tone_wav(text: str, sample_rate: int = 16000) -> bytes:
    """按文本长度生成一段带"音节"包络的提示音，仅用于驱动口型联调。

    不是语音，也不冒充 TTS 输出；只为让浏览器端的幅度口型有东西可跟。
    """
    duration = min(4.0, max(0.8, len(text) * 0.06))
    total = int(sample_rate * duration)
    frames = array("h")
    for index in range(total):
        t = index / sample_rate
        phase = (t % 0.18) / 0.18
        envelope = math.sin(math.pi * min(1.0, phase / 0.7)) ** 2 if phase < 0.7 else 0.0
        frequency = 180 + 40 * math.sin(2 * math.pi * t / 0.9)
        frames.append(int(envelope * 9000 * math.sin(2 * math.pi * frequency * t)))

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames.tobytes())
    return buffer.getvalue()


class FakeASR:
    name = "fake-asr"

    async def transcribe(self, request: ASRRequest) -> ASRResult:
        started = time.perf_counter()
        await asyncio.sleep(0.02)
        text = FAKE_TRANSCRIPT if request.audio else ""
        return ASRResult(
            text=text,
            confidence=0.93 if text else None,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class FakeLLM:
    name = "fake-llm"
    supports_streaming = True

    def __init__(self, answer: str = FAKE_ANSWER) -> None:
        self._answer = answer

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        chunks: list[str] = []
        async for chunk in self.stream(messages):
            chunks.append(chunk)
        return "".join(chunks)

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        step = 6
        for start in range(0, len(self._answer), step):
            await asyncio.sleep(0.008)
            yield self._answer[start : start + step]


class FakeTTS:
    name = "fake-tts"
    supports_streaming = False

    async def synthesize(self, text: str, *, voice: str | None = None) -> TTSResult:
        started = time.perf_counter()
        await asyncio.sleep(0.02)
        audio = synthesize_tone_wav(text)
        return TTSResult(
            audio=audio,
            mime="audio/wav",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class FakeScorer:
    name = "fake-scorer"

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        await asyncio.sleep(0.02)
        match = re.search(r"题目 id：([^\s，,]+)", user_prompt) or re.search(
            r"id=([A-Za-z0-9_-]+)", user_prompt
        )
        question_id = match.group(1) if match else "0"
        return (
            '{"questions":[{"id":"%s","score":70,'
            '"why":"方向对，但没说清什么时候会失手",'
            '"misconception_hit":false,"certain":false}],'
            '"session_misconception":null}' % question_id
        )


class FakeEmbedder:
    """确定性归一化向量；只用于离线联调与测试，不冒充真实语义。"""

    name = "fake-embedding"
    model = "fake"

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        while len(values) < self.dim:
            values.extend((byte / 127.5) - 1.0 for byte in digest)
            digest = hashlib.sha256(digest).digest()
        vector = values[: self.dim]
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class FakeSearch:
    """确定性搜索结果；只用于 fake 模式与测试。"""

    name = "fake-search"

    def __init__(self, hits: Sequence[SearchHit] | None = None) -> None:
        self._hits = tuple(hits if hits is not None else FAKE_SEARCH_HITS)

    async def search(
        self, query: str, *, max_results: int = 5
    ) -> list[SearchHit]:
        return list(self._hits[:max_results])


class NullSearch:
    """未配置搜索时的空实现；不伪造任何出处。"""

    name = "search-off"

    async def search(
        self, query: str, *, max_results: int = 5
    ) -> list[SearchHit]:
        return []
