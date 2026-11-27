"""音频格式辅助：探针与 ASR 验收共用。"""

from __future__ import annotations

from pathlib import Path

SAMPLE_SUFFIX_MIME = {
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}


def mime_for_path(path: Path) -> str | None:
    return SAMPLE_SUFFIX_MIME.get(path.suffix.lower())
