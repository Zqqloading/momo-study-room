from __future__ import annotations

import json

from core.concepts import Concept, Source
from core.lecture import build_lecture_messages, fallback_lecture, parse_lecture


def _concept() -> Concept:
    return Concept(
        id="agent-loop",
        name="Agent 循环",
        aliases=(),
        plain_def="模型自己决定下一步，执行工具后把结果放回上下文再继续。",
        difficulty=2,
        prerequisites=(),
        source=Source(url="https://example.com/a", excerpt="循环 = 想、做、看。"),
    )


def test_parse_lecture_returns_single_paragraph() -> None:
    raw = json.dumps({"concept": "先说概念"})
    assert parse_lecture(raw) == "先说概念。"


def test_parse_lecture_ignores_legacy_structure_field() -> None:
    raw = json.dumps({"concept": "只说概念。", "structure": "这里不该出现"})
    assert parse_lecture(raw) == "只说概念。"


def test_parse_lecture_tolerates_code_fence() -> None:
    raw = '```json\n{"concept": "概念。"}\n```'
    assert parse_lecture(raw) == "概念。"


def test_parse_lecture_rejects_output_without_json() -> None:
    from core.scoring import ScoringError

    try:
        parse_lecture("我直接说了答案")
    except ScoringError:
        pass
    else:  # pragma: no cover
        raise AssertionError("应该抛 ScoringError")


def test_fallback_lecture_mentions_definition() -> None:
    text = fallback_lecture(_concept())
    assert "模型自己决定下一步" in text
    assert text.endswith("。")


def test_build_lecture_messages_is_concept_only() -> None:
    system, user = build_lecture_messages(_concept())
    assert "不要分析题目" in system
    assert "不要提前给答案" in system
    assert "Agent 循环" in user
    assert "模型自己决定下一步" in user
    assert "这道题" not in user
