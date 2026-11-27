from __future__ import annotations

import asyncio
import ast
import json
from pathlib import Path

import numpy as np
import pytest

from bff.providers.fake import FakeEmbedder
from bff.question_generation import BffQuestionGenerator, build_context, build_contexts
from core.concepts import Concept, Source
from core.db import connect, init_schema
from core.models import ConceptState
from core.question_generation import (
    QUESTION_TYPES,
    GenerationError,
    build_session_plan,
)
from core.store import Store

EXCERPT = "MVP 能把验证范围压到核心流程，先看真实用户是否愿意用。"
PARENT_ONE = (
    EXCERPT
    + "完整版会提前投入未验证的功能、设计和交付成本。"
)
PARENT_TWO = "合同承诺需要分级，复杂任务要走人工复核。"

_QUESTION_TEXT = {
    "concept": "为什么 MVP 能降低验证成本？如果直接做完整版，多花的钱主要花在哪？",
    "business": "某公司要在两周内交付 MVP，预算有限。你会先做什么、产出什么、怎么判断有效？",
    "tradeoff": "团队有两种做法：A 全量上线，B 先做核心流程。你会选哪个？放弃什么？什么条件下会反转？",
    "cost_risk": "如果准确率承诺写进合同，会有哪些成本和风险？由谁承担、怎么兜底？至少两项。",
    "synthesis": "客户预算有限、要求两个月上线，并考核准确率。请做决策：选什么方案、依据是什么、边界和失败信号是什么？",
}

_MUST_HAVE = {
    "concept": ("说清 MVP 缩小验证范围", "说清完整版提前投入的成本"),
    "business": ("说清先做的任务", "说清产出和判断标准"),
    "tradeoff": ("说清选择", "说清放弃的代价", "说清反转条件"),
    "cost_risk": ("说清两项成本或风险", "说清承担者和兜底"),
    "synthesis": ("说清决策", "说清依据与边界", "说清失败信号"),
}


def make_concept(concept_id: str = "mvp") -> Concept:
    return Concept(
        id=concept_id,
        name="MVP",
        aliases=("最小可行性产品",),
        plain_def="MVP 是最小可行性产品",
        difficulty=1,
        prerequisites=(),
        source=Source(
            url="https://example.com/m", excerpt=EXCERPT
        ),
    )


def make_store(*, with_retrieval: bool = True) -> Store:
    conn = connect(":memory:")
    init_schema(conn)
    store = Store(conn)
    store.upsert_concept(ConceptState(id="mvp", status="active"))
    store.upsert_material(
        material_id="m",
        title="M",
        path="materials/m.md",
        format="md",
        content_hash="h1",
        version=1,
        added_at="2026-11-25T00:00:00",
        status="active",
        source_url="https://example.com/m",
        tags_json=None,
    )
    store.insert_chunks(
        [
            {
                "id": "m-v1-parent-001",
                "material_id": "m",
                "material_version": 1,
                "parent_id": None,
                "level": "parent",
                "heading_path": "MVP",
                "text": PARENT_ONE,
                "content_hash": "p1",
                "token_count": 50,
                "ordinal": 1,
                "source_url": "https://example.com/m",
            },
            {
                "id": "m-v1-child-001",
                "material_id": "m",
                "material_version": 1,
                "parent_id": "m-v1-parent-001",
                "level": "child",
                "heading_path": "MVP 定义",
                "text": EXCERPT,
                "content_hash": "c1",
                "token_count": 20,
                "ordinal": 2,
                "source_url": "https://example.com/m",
            },
            {
                "id": "m-v1-parent-002",
                "material_id": "m",
                "material_version": 1,
                "parent_id": None,
                "level": "parent",
                "heading_path": "合同",
                "text": PARENT_TWO,
                "content_hash": "p2",
                "token_count": 20,
                "ordinal": 3,
                "source_url": "https://example.com/m",
            },
            {
                "id": "m-v1-child-002",
                "material_id": "m",
                "material_version": 1,
                "parent_id": "m-v1-parent-002",
                "level": "child",
                "heading_path": "合同承诺",
                "text": PARENT_TWO,
                "content_hash": "c2",
                "token_count": 20,
                "ordinal": 4,
                "source_url": "https://example.com/m",
            },
        ]
    )
    store.upsert_concept_source(
        concept_id="mvp", chunk_id="m-v1-child-001", excerpt=EXCERPT
    )
    if with_retrieval:
        store.rebuild_fts()
        store.upsert_embedding(
            chunk_id="m-v1-child-002",
            model="fake",
            dim=3,
            vector=np.asarray([1.0, 0.0, 0.0], dtype=np.float32).tobytes(),
            created_at="2026-11-25T00:00:00",
        )
    return store


def make_plan():
    return build_session_plan(main_concept=make_concept(), review_concept=None)


def question_payload(
    slot: int,
    question_type: str,
    *,
    excerpt: str = EXCERPT,
) -> dict:
    return {
        "slot": slot,
        "concept_id": "mvp",
        "question_type": question_type,
        "question_text": _QUESTION_TEXT[question_type],
        "reference_answer": (
            "先把验证范围压到核心流程，再根据客户反馈决定是否扩展，"
            "避免提前投入未验证的功能和交付成本。"
        ),
        "must_have": list(_MUST_HAVE[question_type]),
        "red_flags": ["只背定义，没有业务判断"],
        "source_ref": 1,
        "source_excerpt": excerpt,
    }


def generation_raw(
    *, excerpts: dict[int, str] | None = None, slots: range | list[int] | None = None
) -> str:
    chosen = list(slots or range(1, 6))
    payload = [
        question_payload(
            slot,
            QUESTION_TYPES[slot - 1],
            excerpt=(excerpts or {}).get(slot, EXCERPT),
        )
        for slot in chosen
    ]
    return json.dumps({"questions": payload}, ensure_ascii=False)


class ScriptedGenerationLLM:
    name = "scripted-generation"

    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return str(item)


def test_build_context_puts_primary_first_and_dedups() -> None:
    store = make_store()
    try:
        contexts = asyncio.run(
            build_contexts(store, FakeEmbedder(3), make_plan())
        )
        context = contexts["mvp"]

        assert context.chunks[0].origin == "primary"
        assert context.chunks[0].ref == 1
        assert context.chunks[0].chunk_id == "m-v1-child-001"
        assert context.chunks[0].parent_chunk_id == "m-v1-parent-001"
        assert context.chunks[0].text.startswith(EXCERPT)
        assert len(context.chunks) <= 6
        assert all(
            chunk.origin == "retrieval" for chunk in context.chunks[1:]
        )
        assert all(
            chunk.parent_chunk_id != "m-v1-parent-001"
            for chunk in context.chunks[1:]
        )
    finally:
        store.close()


def test_build_context_without_retrieval_keeps_primary_only() -> None:
    store = make_store(with_retrieval=False)
    try:
        context = asyncio.run(
            build_context(store, FakeEmbedder(3), make_concept())
        )

        assert [chunk.origin for chunk in context.chunks] == ["primary"]
    finally:
        store.close()


def test_build_context_requires_primary_source() -> None:
    store = make_store()
    try:
        with pytest.raises(GenerationError, match="主出处"):
            asyncio.run(
                build_context(
                    store, FakeEmbedder(3), make_concept("missing")
                )
            )
    finally:
        store.close()


def test_generator_returns_generated_set_with_meta() -> None:
    store = make_store()
    try:
        llm = ScriptedGenerationLLM([generation_raw()])
        generator = BffQuestionGenerator(store, FakeEmbedder(3), llm)

        generated = asyncio.run(generator.generate(make_plan()))

        assert [question.slot for question in generated.questions] == [
            1,
            2,
            3,
            4,
            5,
        ]
        assert generated.questions[0].source_chunk_id == "m-v1-child-001"
        assert generated.questions[0].source_url == "https://example.com/m"
        assert [
            level["score"] for level in generated.questions[0].rubric["levels"]
        ] == [0, 40, 70, 90, 100]
        assert generated.meta["origin"] == "generated"
        assert generated.meta["model"] == "deepseek-chat"
        assert generated.meta["prompt_version"] == "qgen-v1"
        assert generated.meta["repair_count"] == 0
        assert generated.meta["validation"] == "passed"
        assert all(
            isinstance(chunk_id, str)
            for chunk_id in generated.meta["retrieved_chunk_ids"]
        )
        assert len(llm.calls) == 1
    finally:
        store.close()


def test_generator_repairs_bad_excerpt_once() -> None:
    store = make_store()
    try:
        llm = ScriptedGenerationLLM(
            [
                generation_raw(excerpts={3: "这句话不在材料里。"}),
                generation_raw(slots=[3]),
            ]
        )
        generator = BffQuestionGenerator(store, FakeEmbedder(3), llm)

        generated = asyncio.run(generator.generate(make_plan()))

        assert generated.meta["repair_count"] == 1
        assert generated.questions[2].source_excerpt == EXCERPT
        assert len(llm.calls) == 2
        assert "只重写失败槽位" in llm.calls[1][0]
    finally:
        store.close()


def test_generator_repairs_parse_failure_with_full_set() -> None:
    store = make_store()
    try:
        llm = ScriptedGenerationLLM(["not json", generation_raw()])
        generator = BffQuestionGenerator(store, FakeEmbedder(3), llm)

        generated = asyncio.run(generator.generate(make_plan()))

        assert generated.meta["repair_count"] == 1
        assert "1" in llm.calls[1][1] and "5" in llm.calls[1][1]
    finally:
        store.close()


def test_generator_raises_when_repair_still_fails() -> None:
    store = make_store()
    try:
        llm = ScriptedGenerationLLM(
            [
                generation_raw(excerpts={3: "这句话不在材料里。"}),
                generation_raw(excerpts={3: "还是不在材料里。"}, slots=[3]),
            ]
        )
        generator = BffQuestionGenerator(store, FakeEmbedder(3), llm)

        with pytest.raises(GenerationError, match="修复后仍不合法"):
            asyncio.run(generator.generate(make_plan()))
    finally:
        store.close()


def test_generator_wraps_provider_errors() -> None:
    store = make_store()
    try:
        llm = ScriptedGenerationLLM([RuntimeError("timeout")])
        generator = BffQuestionGenerator(store, FakeEmbedder(3), llm)

        with pytest.raises(GenerationError, match="timeout"):
            asyncio.run(generator.generate(make_plan()))
    finally:
        store.close()


def test_generation_does_not_touch_search_hot_items_or_bank() -> None:
    store = make_store()
    try:
        touched: list[str] = []

        def forbidden(*args, **kwargs):
            touched.append("forbidden")
            raise AssertionError("出题不得读写热项或题库")

        store.list_hot_items = forbidden  # type: ignore[method-assign]
        store.hot_items_for_query = forbidden  # type: ignore[method-assign]
        store.import_question_bank = forbidden  # type: ignore[method-assign]
        llm = ScriptedGenerationLLM([generation_raw()])
        generator = BffQuestionGenerator(store, FakeEmbedder(3), llm)

        asyncio.run(generator.generate(make_plan()))

        assert touched == []
        assert not hasattr(generator, "search")
    finally:
        store.close()


def test_generation_modules_do_not_import_search() -> None:
    for path in (
        Path("core/question_generation.py"),
        Path("bff/question_generation.py"),
    ):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
        assert not any(
            "tavily" in module or "search" in module for module in modules
        ), (path, modules)
        assert "hot_items" not in source
        assert "question_bank" not in source
