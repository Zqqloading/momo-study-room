from __future__ import annotations

import asyncio
import json

from core.extract import source_url_for
from core.extraction import ExistingConcept, Extractor
from core.ingestion import Chunk

PARENT_TEXT = (
    "Agent 是能自己决定下一步的程序。"
    "工具调用让模型调用外部工具拿到结果。"
    "上下文窗口是模型一次能看到的 token 上限。"
    "记忆让 agent 记住之前发生的事。"
)


def parent(text: str = PARENT_TEXT, chunk_id: str = "m-v1-parent-001") -> Chunk:
    return Chunk(
        id=chunk_id,
        material_id="m",
        material_version=1,
        level="parent",
        parent_id=None,
        heading_path="Agent 基础",
        text=text,
        token_count=100,
        ordinal=1,
        content_hash="hash",
    )


class FakeScorer:
    name = "fake"

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        return self.responses.pop(0)


def run(scorer: FakeScorer, parents: list[Chunk], existing: tuple[ExistingConcept, ...] = ()):
    return asyncio.run(
        Extractor(scorer).extract(
            parents,
            source_url="https://example.com/a",
            material_path="materials/a.md",
            existing=existing,
        )
    )


def payload(*items: dict[str, object]) -> str:
    return json.dumps({"concepts": list(items)}, ensure_ascii=False)


def candidate(name: str, excerpt: str, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": name,
        "aliases": [],
        "plain_def": "一句短定义",
        "prerequisites": [],
        "difficulty": 1,
        "source_excerpt": excerpt,
    }
    data.update(overrides)
    return data


def test_source_url_falls_back_to_local_path() -> None:
    assert source_url_for({"path": "materials/a.md"}, "x") == "local://materials/a.md"
    assert (
        source_url_for({"path": "materials/a.md", "source_url": "https://example.com/a"}, "x")
        == "https://example.com/a"
    )


def test_extracts_candidates_and_resolves_same_batch_prerequisite() -> None:
    scorer = FakeScorer(
        [
            payload(
                candidate("Agent", "Agent 是能自己决定下一步的程序", difficulty=1),
                candidate(
                    "工具调用",
                    "工具调用让模型调用外部工具",
                    aliases=["function calling"],
                    prerequisites=["Agent"],
                    difficulty=2,
                ),
            )
        ]
    )
    report = run(scorer, [parent()])

    assert [item.name for item in report.candidates] == ["Agent", "工具调用"]
    first, second = report.candidates
    assert first.id == "agent"
    assert first.source_url == "https://example.com/a"
    assert first.material_path == "materials/a.md"
    assert second.prerequisites == ("agent",)
    assert second.prerequisite_names == ("Agent",)
    assert second.aliases == ("function calling",)


def test_existing_alias_resolves_as_prerequisite() -> None:
    existing = (ExistingConcept(id="agent", name="Agent", aliases=("智能体",)),)
    scorer = FakeScorer(
        [payload(candidate("工具调用", "工具调用让模型调用外部工具", prerequisites=["智能体"]))]
    )
    report = run(scorer, [parent()], existing=existing)

    assert report.candidates[0].prerequisites == ("agent",)


def test_hard_gates_drop_candidates() -> None:
    scorer = FakeScorer(
        [
            payload(
                candidate("长定义", "Agent 是能自己决定下一步的程序", plain_def="x" * 61),
                candidate("套话", "Agent 是能自己决定下一步的程序", plain_def="本段介绍了 agent 的概念"),
                candidate("错摘录", "这句话不在原文里"),
            )
        ]
    )
    report = run(scorer, [parent()])

    assert report.candidates == ()
    text = "\n".join(report.warnings)
    assert "超过 60 字" in text
    assert "含套话" in text
    assert "不在父块原文" in text


def test_max_three_concepts_per_parent() -> None:
    scorer = FakeScorer(
        [
            payload(
                candidate("Agent", "Agent 是能自己决定下一步的程序"),
                candidate("工具调用", "工具调用让模型调用外部工具"),
                candidate("上下文窗口", "上下文窗口是模型一次能看到的 token 上限"),
                candidate("记忆", "记忆让 agent 记住之前发生的事"),
            )
        ]
    )
    report = run(scorer, [parent()])

    assert len(report.candidates) == 3
    assert any("只保留前 3 个" in warning for warning in report.warnings)


def test_duplicate_names_are_dropped() -> None:
    existing = (ExistingConcept(id="agent", name="Agent"),)
    scorer = FakeScorer(
        [
            payload(
                candidate("Agent", "Agent 是能自己决定下一步的程序"),
                candidate("工具调用", "工具调用让模型调用外部工具"),
                candidate("工具调用", "工具调用让模型调用外部工具"),
            )
        ]
    )
    report = run(scorer, [parent()], existing=existing)

    assert [item.name for item in report.candidates] == ["工具调用"]
    assert any("重复" in warning for warning in report.warnings)


def test_duplicate_alias_is_dropped() -> None:
    scorer = FakeScorer(
        [
            payload(
                candidate("Agent", "Agent 是能自己决定下一步的程序"),
                candidate("工具调用", "工具调用让模型调用外部工具", aliases=["Agent"]),
            )
        ]
    )
    report = run(scorer, [parent()])

    assert [item.name for item in report.candidates] == ["Agent"]
    assert any("重复" in warning for warning in report.warnings)


def test_invalid_json_retries_once_then_succeeds() -> None:
    scorer = FakeScorer(
        ["not json", payload(candidate("Agent", "Agent 是能自己决定下一步的程序"))]
    )
    report = run(scorer, [parent()])

    assert scorer.calls == 2
    assert len(report.candidates) == 1
    assert report.failures == ()


def test_two_failures_record_failure_and_continue() -> None:
    scorer = FakeScorer(["not json", "still not json"])
    report = run(scorer, [parent()])

    assert scorer.calls == 2
    assert report.candidates == ()
    assert len(report.failures) == 1
    assert report.failures[0].chunk_id == "m-v1-parent-001"


def test_soft_flags_do_not_drop() -> None:
    scorer = FakeScorer(
        [
            payload(
                candidate(
                    "这是一个非常长的概念名字，长到不像术语",
                    "Agent 是能自己决定下一步的程序",
                ),
                candidate("短摘录", "Agent"),
            )
        ]
    )
    report = run(scorer, [parent()])

    assert [item.name for item in report.candidates] == [
        "这是一个非常长的概念名字，长到不像术语",
        "短摘录",
    ]
    assert "name_not_term" in report.candidates[0].flags
    assert "short_excerpt" in report.candidates[1].flags


def test_unresolved_prerequisite_is_dropped_with_flag() -> None:
    scorer = FakeScorer(
        [
            payload(
                candidate(
                    "工具调用",
                    "工具调用让模型调用外部工具",
                    prerequisites=["不存在的前置"],
                )
            )
        ]
    )
    report = run(scorer, [parent()])

    assert report.candidates[0].prerequisites == ()
    assert "prerequisite_dropped" in report.candidates[0].flags
    assert any("未找到" in warning for warning in report.warnings)
