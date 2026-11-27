from __future__ import annotations

import json
from dataclasses import replace

import pytest

from core.concepts import Concept, Source
from core.question_generation import (
    ContextChunk,
    GenerationContext,
    GenerationError,
    QuestionDraft,
    apply_repair,
    build_generation_messages,
    build_repair_messages,
    build_rubric,
    build_session_plan,
    parse_generation,
    to_generated_question,
    validate_question_set,
)

_QUESTION_TEXT = {
    "concept": "为什么这道材料里的做法能降低验证成本？如果直接做完整版，多花的钱主要花在哪？",
    "business": "某公司要在两周内交付核心流程，预算有限。你会先做什么、产出什么、怎么判断有效？",
    "tradeoff": "团队有两种做法：A 全量上线，B 先做核心流程。你会选哪个？放弃什么？什么条件下会反转？",
    "cost_risk": "如果准确率承诺写进合同，会有哪些成本和风险？由谁承担、怎么兜底？至少两项。",
    "synthesis": "客户预算有限、要求两个月上线，并考核准确率。请做决策：选什么方案、依据是什么、边界和失败信号是什么？",
}

_MUST_HAVE = {
    "concept": ("说清做法缩小验证范围", "说清完整版提前投入的成本"),
    "business": ("说清先做的任务", "说清产出和判断标准"),
    "tradeoff": ("说清选择", "说清放弃的代价", "说清反转条件"),
    "cost_risk": ("说清两项成本或风险", "说清承担者和兜底"),
    "synthesis": ("说清决策", "说清依据与边界", "说清失败信号"),
}


def make_concept(concept_id: str) -> Concept:
    return Concept(
        id=concept_id,
        name=concept_id.upper(),
        aliases=(),
        plain_def=f"{concept_id} 的简要定义",
        difficulty=1,
        prerequisites=(),
        source=Source(
            url=f"https://example.com/{concept_id}",
            excerpt=f"{concept_id} 的出处摘录",
        ),
    )


def make_context(concept_id: str) -> GenerationContext:
    sentences = (
        f"{concept_id} 能把验证范围压到核心流程，先看真实用户是否愿意用。",
        f"{concept_id} 在预算有限时，团队应先交付核心流程，再根据反馈扩展。",
        f"{concept_id} 的合同承诺需要分级，复杂任务要走人工复核。",
    )
    return GenerationContext(
        concept_id=concept_id,
        chunks=tuple(
            ContextChunk(
                ref=index,
                chunk_id=f"m-v1-child-00{index}",
                parent_chunk_id="m-v1-parent-001",
                heading_path=f"{concept_id} 小节 {index}",
                text=text,
                source_url="https://example.com/m",
                origin="primary" if index == 1 else "retrieval",
            )
            for index, text in enumerate(sentences, start=1)
        ),
    )


@pytest.fixture
def plan():
    return build_session_plan(
        main_concept=make_concept("mvp"), review_concept=make_concept("rag")
    )


@pytest.fixture
def contexts():
    return {"mvp": make_context("mvp"), "rag": make_context("rag")}


def good_drafts(plan, contexts) -> tuple[QuestionDraft, ...]:
    return tuple(
        QuestionDraft(
            slot=slot.slot,
            concept_id=slot.concept_id,
            question_type=slot.question_type,
            question_text=_QUESTION_TEXT[slot.question_type],
            reference_answer=(
                "先把验证范围压到核心流程，再根据客户反馈决定是否扩展，"
                "避免提前投入未验证的功能和交付成本。"
            ),
            must_have=_MUST_HAVE[slot.question_type],
            red_flags=("只背定义，没有业务判断",),
            source_ref=1,
            source_excerpt=contexts[slot.concept_id].chunks[0].text,
        )
        for slot in plan.slots
    )


def mutate(
    drafts: tuple[QuestionDraft, ...], index: int, **changes
) -> tuple[QuestionDraft, ...]:
    updated = list(drafts)
    updated[index] = replace(updated[index], **changes)
    return tuple(updated)


def draft_payload(draft: QuestionDraft) -> dict:
    return {
        "slot": draft.slot,
        "concept_id": draft.concept_id,
        "question_type": draft.question_type,
        "question_text": draft.question_text,
        "reference_answer": draft.reference_answer,
        "must_have": list(draft.must_have),
        "red_flags": list(draft.red_flags),
        "source_ref": draft.source_ref,
        "source_excerpt": draft.source_excerpt,
    }


def test_build_rubric_uses_fixed_five_levels() -> None:
    rubric = build_rubric(
        question_type="tradeoff",
        must_have=("说清选择", "说清放弃的代价"),
        red_flags=("只列优缺点",),
        reference_answer="选 B，放弃短期速度。",
    )

    assert [level["score"] for level in rubric["levels"]] == [0, 40, 70, 90, 100]
    assert rubric["must_have"] == ["说清选择", "说清放弃的代价"]
    assert rubric["red_flags"] == ["只列优缺点"]
    assert rubric["reference_answer"] == "选 B，放弃短期速度。"


def test_parse_generation_returns_five_slots(plan, contexts) -> None:
    drafts = good_drafts(plan, contexts)
    raw = json.dumps(
        {"questions": [draft_payload(draft) for draft in drafts]},
        ensure_ascii=False,
    )

    parsed = parse_generation(raw, plan)

    assert [draft.slot for draft in parsed] == [1, 2, 3, 4, 5]
    assert parsed[0].question_text == drafts[0].question_text
    assert parsed[3].must_have == drafts[3].must_have


def test_parse_generation_accepts_repair_subset(plan, contexts) -> None:
    drafts = good_drafts(plan, contexts)
    raw = json.dumps({"questions": [draft_payload(drafts[2])]}, ensure_ascii=False)

    parsed = parse_generation(raw, plan, slots=[3])

    assert [draft.slot for draft in parsed] == [3]


def test_parse_generation_rejects_missing_slots(plan, contexts) -> None:
    drafts = good_drafts(plan, contexts)
    raw = json.dumps(
        {"questions": [draft_payload(draft) for draft in drafts[:2]]},
        ensure_ascii=False,
    )

    with pytest.raises(GenerationError, match="槽位不完整"):
        parse_generation(raw, plan)


def test_parse_generation_rejects_missing_field(plan, contexts) -> None:
    drafts = good_drafts(plan, contexts)
    payload = [draft_payload(draft) for draft in drafts]
    payload[0].pop("reference_answer")
    raw = json.dumps({"questions": payload}, ensure_ascii=False)

    with pytest.raises(GenerationError, match="reference_answer"):
        parse_generation(raw, plan)


def test_to_generated_question_maps_source_and_rubric(plan, contexts) -> None:
    drafts = good_drafts(plan, contexts)
    chunk = contexts["mvp"].chunks[0]

    question = to_generated_question(drafts[0], chunk)

    assert question.source_chunk_id == "m-v1-child-001"
    assert question.source_url == "https://example.com/m"
    assert question.source_excerpt == chunk.text
    assert question.reference_answer == drafts[0].reference_answer
    assert [level["score"] for level in question.rubric["levels"]] == [
        0,
        40,
        70,
        90,
        100,
    ]


def test_validate_accepts_good_set(plan, contexts) -> None:
    result = validate_question_set(good_drafts(plan, contexts), contexts, plan)

    assert result.ok
    assert result.errors == ()
    assert result.warnings == ()
    assert result.failed_slots == ()


@pytest.mark.parametrize(
    ("index", "changes", "message", "failed_slot"),
    [
        (0, {"concept_id": "other"}, "概念应为", 1),
        (0, {"question_type": "business"}, "题型应为", 1),
        (0, {"question_text": ""}, "题干为空", 1),
        (0, {"question_text": "测" * 201}, "超过 200 字", 1),
        (
            0,
            {"question_text": "请说明这个概念在后端实现里怎么用？"},
            "代码实现禁词",
            1,
        ),
        (0, {"reference_answer": ""}, "缺少参考答案", 1),
        (0, {"must_have": ("只有一条",)}, "must_have", 1),
        (0, {"must_have": tuple(f"要点{i}" for i in range(6))}, "must_have", 1),
        (0, {"red_flags": ()}, "red_flags", 1),
        (0, {"source_ref": 9}, "source_ref", 1),
        (0, {"source_excerpt": "这句话不在材料里。"}, "逐字", 1),
        (1, {"question_text": _QUESTION_TEXT["concept"]}, "重复", 2),
    ],
)
def test_validate_hard_failures(
    plan, contexts, index, changes, message, failed_slot
) -> None:
    drafts = mutate(good_drafts(plan, contexts), index, **changes)

    result = validate_question_set(drafts, contexts, plan)

    assert not result.ok
    assert any(message in error for error in result.errors)
    assert failed_slot in result.failed_slots


@pytest.mark.parametrize(
    ("index", "changes", "message"),
    [
        (
            0,
            {"question_text": "什么是这个概念？请给出定义。"},
            "概念题像定义题",
        ),
        (
            1,
            {"question_text": "你会怎么使用这个概念？"},
            "缺少具体业务场景",
        ),
        (
            1,
            {"question_text": "客户团队预算有限，这个概念在业务场景中的价值是什么？"},
            "缺少具体动作",
        ),
        (
            2,
            {"question_text": "这个概念和替代方案各有什么优缺点？"},
            "取舍题缺少",
        ),
        (
            3,
            {"question_text": "如果承诺写进合同，由谁承担、怎么兜底？请至少说出两项。"},
            "缺少成本或风险要素",
        ),
        (
            3,
            {"question_text": "合同承诺会带来哪些成本和风险？"},
            "缺少承担者或兜底",
        ),
        (
            4,
            {"question_text": "请描述这个概念在客户项目里的作用。"},
            "综合题缺少",
        ),
        (
            3,
            {"must_have": ("说清先做什么", "说清怎么判断有效")},
            "must_have 与题型",
        ),
        (
            0,
            {"must_have": ("说清定义", "说清含义")},
            "must_have 只考定义",
        ),
    ],
)
def test_validate_soft_warnings(plan, contexts, index, changes, message) -> None:
    drafts = mutate(good_drafts(plan, contexts), index, **changes)

    result = validate_question_set(drafts, contexts, plan)

    assert result.ok
    assert any(message in warning for warning in result.warnings)


def test_validate_warns_short_excerpt(plan, contexts) -> None:
    short = contexts["mvp"].chunks[0].text[:5]
    drafts = mutate(good_drafts(plan, contexts), 0, source_excerpt=short)

    result = validate_question_set(drafts, contexts, plan)

    assert result.ok
    assert any("source_excerpt 过短" in warning for warning in result.warnings)


def test_validate_warns_repeat_of_previous_question(plan, contexts) -> None:
    drafts = good_drafts(plan, contexts)

    result = validate_question_set(
        drafts,
        contexts,
        plan,
        previous_texts={"mvp": (drafts[0].question_text,)},
    )

    assert result.ok
    assert any("高度相似" in warning for warning in result.warnings)


def test_apply_repair_replaces_failed_slot(plan, contexts) -> None:
    drafts = good_drafts(plan, contexts)
    bad = mutate(drafts, 2, source_excerpt="这句话不在材料里。")
    result = validate_question_set(bad, contexts, plan)
    assert result.failed_slots == (3,)

    merged = apply_repair(
        bad,
        (replace(bad[2], source_excerpt=drafts[2].source_excerpt),),
        failed_slots=result.failed_slots,
        contexts=contexts,
        plan=plan,
    )

    assert merged[2].source_excerpt == drafts[2].source_excerpt


def test_apply_repair_still_invalid_raises(plan, contexts) -> None:
    drafts = good_drafts(plan, contexts)
    bad = mutate(drafts, 2, source_excerpt="这句话不在材料里。")
    result = validate_question_set(bad, contexts, plan)

    with pytest.raises(GenerationError, match="修复后仍不合法"):
        apply_repair(
            bad,
            (bad[2],),
            failed_slots=result.failed_slots,
            contexts=contexts,
            plan=plan,
        )


def test_apply_repair_rejects_wrong_slots(plan, contexts) -> None:
    drafts = good_drafts(plan, contexts)

    with pytest.raises(GenerationError, match="修复槽位不匹配"):
        apply_repair(
            drafts,
            (drafts[2],),
            failed_slots=(4,),
            contexts=contexts,
            plan=plan,
        )


def test_generation_messages_include_slots_and_contexts(plan, contexts) -> None:
    system, user = build_generation_messages(plan, contexts)

    assert "概念理解" in system
    assert "禁止代码实现词" in system
    assert "[1]" in user
    assert "slot | concept_id" in user
    assert "mvp" in user and "rag" in user


def test_repair_messages_only_target_failed_slots(plan, contexts) -> None:
    drafts = good_drafts(plan, contexts)

    system, user = build_repair_messages(
        plan,
        contexts,
        drafts,
        failed_slots=(3,),
        errors=("槽位 3：source_excerpt 不是原文逐字子串",),
    )

    assert "只重写失败槽位" in system
    assert "失败槽位" in user
    assert "槽位 3" in user
    assert "已通过槽位" in user
    assert "source_excerpt 不是原文逐字子串" in user
