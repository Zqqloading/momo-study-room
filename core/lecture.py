"""开场讲解：只讲今天这个概念（是什么、为什么重要、一个例子）。"""

from __future__ import annotations

from typing import Any

from .scoring import extract_json_object

CONCEPT_MAX_CHARS = 160

LECTURE_SYSTEM_PROMPT = (
    "你是用户的学习搭子，开始学习前先用一分钟介绍今天要学的知识点。"
    "只讲这个点本身：它是什么、为什么重要、一个具体例子。"
    "不要分析题目，不要提前给答案或评分要点，不要替用户作答。"
    "用口语、短句、第二人称。"
    f'只输出 JSON：{{"concept": "概念介绍，不超过 {CONCEPT_MAX_CHARS} 字"}}。'
)


def build_lecture_messages(concept: Any) -> tuple[str, str]:
    lines = [
        f"知识点：{concept.name}",
        f"一句话定义：{concept.plain_def}",
        f"材料原句：{concept.source.excerpt}",
        "",
        f"一句话到三句话讲清楚，总共不超过 {CONCEPT_MAX_CHARS} 字。",
    ]
    return LECTURE_SYSTEM_PROMPT, "\n".join(lines)


def fallback_lecture(concept: Any) -> str:
    definition = str(concept.plain_def or "").strip().rstrip("。！？. ")
    return f"今天先学这个点：{definition}。"


def parse_lecture(raw: str) -> str:
    payload = extract_json_object(raw)
    concept = str(payload.get("concept") or "").strip()[:CONCEPT_MAX_CHARS]
    if concept and concept[-1] not in "。！？…":
        concept += "。"
    return concept
