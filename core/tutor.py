"""v0 Tutor：单题的问法与评分后的反馈文本。

题目来自题库，v0 不改写；反馈先只用模板，真实 LLM 改写放到 v1。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tutor:
    def ask(self, text: str) -> str:
        return text

    def feedback(self, score: int, why: str) -> str:
        return f"{score} 分。{why}"
