"""题目音频缓存：命中直接复用，未命中调用 TTS 并落盘。

缓存 key 由文本、音色、模型与格式共同决定；缓存目录不进 git。
失败不写半份文件，调用方决定是否降级为实时合成。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .ports import TTSProvider


class TTSCache:
    def __init__(
        self,
        provider: TTSProvider,
        cache_dir: str | Path,
        *,
        voice: str = "",
        model: str = "",
        output_format: str = "",
    ) -> None:
        self._provider = provider
        self._dir = Path(cache_dir)
        self._voice = voice
        self._model = model
        self._output_format = output_format

    def key(self, text: str) -> str:
        payload = "\x00".join((text, self._voice, self._model, self._output_format))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _paths(self, text: str) -> tuple[Path, Path]:
        key = self.key(text)
        return self._dir / f"{key}.bin", self._dir / f"{key}.mime"

    async def get_or_synthesize(self, text: str) -> tuple[bytes, str]:
        audio_path, mime_path = self._paths(text)
        if audio_path.is_file() and mime_path.is_file():
            return audio_path.read_bytes(), mime_path.read_text(encoding="utf-8").strip()

        result = await self._provider.synthesize(text, voice=self._voice or None)
        if not result.audio:
            return b"", result.mime

        self._dir.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(result.audio)
        mime_path.write_text(result.mime or "audio/mpeg", encoding="utf-8")
        return result.audio, result.mime
