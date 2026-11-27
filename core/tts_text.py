"""把朗读文本切成适合逐句合成的片段。

不支持流式的 TTS（如 DeepSeek）整段合成要等全文合成完才出声；按句切分后
可以逐句合成、逐句发送，让第一句先播出来。纯函数，便于单测。
"""

from __future__ import annotations

import re

MAX_SENTENCE_CHARS = 40
_STRONG_BREAK = re.compile(r"(?<=[。！？；!?;\n])")
_SOFT_BREAK = re.compile(r"(?<=[，、,])")


def split_for_tts(text: str, *, max_chars: int = MAX_SENTENCE_CHARS) -> list[str]:
    """按句切分；单句超长时按逗号合并到接近 max_chars，再不行硬切。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    chunks: list[str] = []
    for sentence in _STRONG_BREAK.split(cleaned):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            chunks.append(sentence)
            continue

        buffer = ""
        for clause in _SOFT_BREAK.split(sentence):
            clause = clause.strip()
            if not clause:
                continue
            if len(clause) > max_chars:
                if buffer:
                    chunks.append(buffer)
                    buffer = ""
                chunks.extend(
                    clause[index : index + max_chars]
                    for index in range(0, len(clause), max_chars)
                )
                continue
            if buffer and len(buffer) + len(clause) > max_chars:
                chunks.append(buffer)
                buffer = ""
            buffer += clause
        if buffer:
            chunks.append(buffer)
    return chunks
