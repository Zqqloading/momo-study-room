"""出题契约：槽位计划、compact 提示词、解析、校验与修复。

模型只写题干/参考答案/要点，题型、槽位与概念归属由程序固定。
这里只做确定性处理，不调用外部服务，也不 import 搜索适配器（ADR 0002）。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol, Sequence

from .concepts import Concept
from .scoring import ScoringError, extract_json_object

QuestionType = Literal["concept", "business", "tradeoff", "cost_risk", "synthesis"]

QUESTION_TYPES: tuple[QuestionType, ...] = (
    "concept",
    "business",
    "tradeoff",
    "cost_risk",
    "synthesis",
)

QUESTION_TYPE_LABELS: dict[str, str] = {
    "concept": "概念理解",
    "business": "业务运用",
    "tradeoff": "取舍权衡",
    "cost_risk": "成本风险",
    "synthesis": "综合判断",
}

RUBRIC_SCORES = (0, 40, 70, 90, 100)

_RUBRIC_LEVEL_TEXT = {
    0: "完全跑偏：没有回答题干，或概念理解错误。",
    40: "部分相关：提到一些相关点，但关键判断缺失或概念混淆。",
    70: "方向正确：覆盖多数 must_have，但场景、代价或边界不完整。",
    90: "要点完整：覆盖 must_have，能结合业务场景，只有少量遗漏。",
    100: "完整准确：覆盖 must_have，避开 red_flags，业务判断清楚。",
}

CODE_IMPLEMENTATION_WORDS = (
    "函数",
    "参数",
    "数据库表",
    "写代码",
    "sql",
    "部署脚本",
    "api 参数",
    "字段",
    "后端实现",
)

MUST_HAVE_MIN = 2
MUST_HAVE_MAX = 5
RED_FLAGS_MIN = 1
RED_FLAGS_MAX = 3
QUESTION_MAX_CHARS = 200
EXCERPT_MIN_CHARS = 12

_SCENARIO_MARKERS = (
    "场景",
    "客户",
    "团队",
    "项目",
    "预算",
    "周期",
    "交付",
    "业务",
    "用户",
    "公司",
    "方案",
    "产品",
)
_JUDGMENT_MARKERS = (
    "如何",
    "怎么",
    "先做",
    "产出",
    "判断",
    "选择",
    "决策",
    "会",
)
_TRADEOFF_MARKERS = ("选", "放弃", "代价", "反转", "条件", "还是")
_COST_RISK_MARKERS = ("成本", "风险")
_FALLBACK_MARKERS = ("承担", "兜底", "缓解", "复核", "回滚", "至少两项")
_SYNTHESIS_MARKERS = ("决策", "选", "依据", "边界", "失败信号", "约束")
_TYPE_REQUIRED_WORDS: dict[str, tuple[str, ...]] = {
    "business": ("场景", "任务", "步骤", "产出", "判断", "动作"),
    "tradeoff": ("选择", "放弃", "代价", "反转", "条件"),
    "cost_risk": ("成本", "风险", "承担", "兜底", "缓解"),
    "synthesis": ("决策", "依据", "边界", "失败信号", "取舍"),
}


class GenerationError(RuntimeError):
    """生成、解析或修复失败；调用方回退旧题库。"""


@dataclass(frozen=True, slots=True)
class Slot:
    slot: int
    concept_id: str
    role: Literal["new", "review"]
    question_type: QuestionType


@dataclass(frozen=True, slots=True)
class SessionPlan:
    kind: Literal["daily", "review"]
    main_concept: Concept | None
    review_concept: Concept | None
    slots: tuple[Slot, ...]


@dataclass(frozen=True, slots=True)
class ContextChunk:
    ref: int
    chunk_id: str
    parent_chunk_id: str | None
    heading_path: str | None
    text: str
    source_url: str
    origin: Literal["primary", "retrieval"]


@dataclass(frozen=True, slots=True)
class GenerationContext:
    concept_id: str
    chunks: tuple[ContextChunk, ...]


@dataclass(frozen=True, slots=True)
class QuestionDraft:
    slot: int
    concept_id: str
    question_type: str
    question_text: str
    reference_answer: str
    must_have: tuple[str, ...]
    red_flags: tuple[str, ...]
    source_ref: int
    source_excerpt: str


@dataclass(frozen=True, slots=True)
class GeneratedQuestion:
    slot: int
    concept_id: str
    question_type: str
    question_text: str
    reference_answer: str
    rubric: dict[str, Any]
    source_chunk_id: str
    source_url: str
    source_excerpt: str


@dataclass(frozen=True, slots=True)
class GeneratedSet:
    questions: tuple[GeneratedQuestion, ...]
    meta: dict[str, Any]


class QuestionGenerator(Protocol):
    async def generate(self, plan: SessionPlan) -> GeneratedSet: ...


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    failed_slots: tuple[int, ...] = ()


def build_session_plan(
    *,
    main_concept: Concept | None,
    review_concept: Concept | None,
) -> SessionPlan:
    """按 5.2 的配比生成固定槽位；模型不参与。"""
    if main_concept is None and review_concept is None:
        raise ValueError("主概念与复习概念不能同时为空")

    if main_concept is not None and review_concept is not None:
        if main_concept.id == review_concept.id:
            roles = {
                "concept": "new",
                "business": "new",
                "tradeoff": "new",
                "cost_risk": "review",
                "synthesis": "review",
            }
            return SessionPlan(
                kind="daily",
                main_concept=main_concept,
                review_concept=review_concept,
                slots=tuple(
                    Slot(index, main_concept.id, roles[qtype], qtype)
                    for index, qtype in enumerate(QUESTION_TYPES, start=1)
                ),
            )
        return SessionPlan(
            kind="daily",
            main_concept=main_concept,
            review_concept=review_concept,
            slots=(
                Slot(1, main_concept.id, "new", "concept"),
                Slot(2, main_concept.id, "new", "business"),
                Slot(3, main_concept.id, "new", "tradeoff"),
                Slot(4, review_concept.id, "review", "cost_risk"),
                Slot(5, review_concept.id, "review", "synthesis"),
            ),
        )

    if main_concept is not None:
        return SessionPlan(
            kind="daily",
            main_concept=main_concept,
            review_concept=None,
            slots=tuple(
                Slot(index, main_concept.id, "new", qtype)
                for index, qtype in enumerate(QUESTION_TYPES, start=1)
            ),
        )

    assert review_concept is not None
    return SessionPlan(
        kind="review",
        main_concept=None,
        review_concept=review_concept,
        slots=tuple(
            Slot(index, review_concept.id, "review", qtype)
            for index, qtype in enumerate(QUESTION_TYPES, start=1)
        ),
    )


def build_rubric(
    *,
    question_type: str,
    must_have: Sequence[str],
    red_flags: Sequence[str],
    reference_answer: str,
) -> dict[str, Any]:
    label = QUESTION_TYPE_LABELS.get(question_type, question_type)
    return {
        "question_type": question_type,
        "levels": [
            {"score": score, "description": f"{label}：{_RUBRIC_LEVEL_TEXT[score]}"}
            for score in RUBRIC_SCORES
        ],
        "must_have": list(must_have),
        "red_flags": list(red_flags),
        "reference_answer": reference_answer,
    }


def build_generation_messages(
    plan: SessionPlan,
    contexts: Mapping[str, GenerationContext],
    *,
    previous_texts: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, str]:
    """拼一次整场出题调用。上下文按概念分组，source_ref 是概念内编号。"""
    system = _generation_system_prompt()
    user = "\n\n".join(
        [
            _concept_blocks(plan, contexts, previous_texts or {}),
            _slot_table(plan),
            _output_schema(),
        ]
    )
    return system, user


def _generation_system_prompt() -> str:
    return (
        "你是 B 端 AI 产品的产品教练，不是程序员。根据给定材料和概念，写 5 道中文开放题。\n"
        "每道题只考业务/产品判断，不考代码实现、不考背诵定义。\n"
        "槽位与题型已给定，不得改变；每题必须引用给定材料中的一段原文。\n\n"
        "题型定义（必须严格按槽位使用）：\n"
        "- concept 概念理解：问为什么需要/解决什么业务问题/不用会怎样/与相邻概念的区别；"
        "不要问“X 是什么”或“X 的定义”。\n"
        "- business 业务运用：给具体业务场景，问怎么用、先做什么、产出什么、怎么判断有效。\n"
        "- tradeoff 取舍权衡：给 A/B 或两种做法，问选哪个、放弃什么、什么条件下反转。\n"
        "- cost_risk 成本风险：问成本、风险、谁承担、怎么兜底，至少两项；"
        "不能只泛泛问“有什么风险”。\n"
        "- synthesis 综合判断：给完整场景与约束，要求做决策、说依据、说边界或失败信号。\n\n"
        "业务视角规则：\n"
        "- 题干必须落到至少一个业务维度：客户、团队、预算、周期、合规、交付、收入、成本、售后。\n"
        "- 禁止代码实现词：函数、参数、数据库表、写代码、SQL、部署脚本、API 参数、字段、后端实现。\n"
        "- 技术概念必须翻译成业务后果；全部是开放题，不能是“以下哪个”或 Yes/No。\n"
        "- 允许构造假设业务场景，但不得伪造数据或案例。\n\n"
        "反背诵规则：\n"
        "- 概念题必须考因果或业务后果；只复述材料原句的回答不算理解。\n"
        "- must_have 写 2-5 条具体判断要点；red_flags 写 1-3 条典型错误。\n\n"
        "溯源规则：\n"
        "- source_ref 指向该概念上下文里的编号；source_excerpt 必须逐字来自该编号正文，"
        "不得改写、概括或拼接。\n"
        "- 优先选完整句，避免标题或单词；摘录要直接支撑题干。\n"
        "- reference_answer 60-120 字，直接给结论；题干 15-200 字。"
    )


def _concept_blocks(
    plan: SessionPlan,
    contexts: Mapping[str, GenerationContext],
    previous_texts: Mapping[str, Sequence[str]],
) -> str:
    concepts: list[Concept] = []
    for concept in (plan.main_concept, plan.review_concept):
        if concept is not None and all(item.id != concept.id for item in concepts):
            concepts.append(concept)

    blocks: list[str] = ["## 概念与材料"]
    for concept in concepts:
        context = contexts.get(concept.id)
        if context is None:
            raise GenerationError(f"概念缺少上下文：{concept.id}")
        lines = [f"### {concept.name}（concept_id: {concept.id}）"]
        if concept.aliases:
            lines.append(f"别名：{'、'.join(concept.aliases)}")
        lines.append(f"定义：{concept.plain_def}")
        lines.append(f"概念出处摘录：{concept.source.excerpt}")
        for chunk in context.chunks:
            heading = f"（{chunk.heading_path}）" if chunk.heading_path else ""
            lines.append(f"[{chunk.ref}]{heading}")
            lines.append(chunk.text.strip())
        recent = [text for text in previous_texts.get(concept.id, ()) if text.strip()]
        if recent:
            lines.append("上一场同概念题干（必须避免重复）：")
            lines.extend(f"- {text.strip()}" for text in recent)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _slot_table(plan: SessionPlan) -> str:
    lines = ["## 槽位与题型（固定，不得改动）", "slot | concept_id | 角色 | 题型"]
    for slot in plan.slots:
        label = QUESTION_TYPE_LABELS[slot.question_type]
        lines.append(
            f"{slot.slot} | {slot.concept_id} | {slot.role} | "
            f"{slot.question_type}（{label}）"
        )
    return "\n".join(lines)


def _output_schema() -> str:
    return (
        "## 输出\n"
        "只返回一个 JSON 对象，不要 Markdown 围栏，不要解释：\n"
        "{\n"
        '  "questions": [\n'
        "    {\n"
        '      "slot": 1,\n'
        '      "concept_id": "<槽位给定>",\n'
        '      "question_type": "<槽位给定>",\n'
        '      "question_text": "<15-200 字>",\n'
        '      "reference_answer": "<60-120 字>",\n'
        '      "must_have": ["<判断要点>", "<判断要点>"],\n'
        '      "red_flags": ["<典型错误>"],\n'
        '      "source_ref": 1,\n'
        '      "source_excerpt": "<上下文逐字摘录>"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "questions 必须恰好 5 条，slot 为 1-5 各一条。"
    )


def build_repair_messages(
    plan: SessionPlan,
    contexts: Mapping[str, GenerationContext],
    drafts: Sequence[QuestionDraft],
    *,
    failed_slots: Sequence[int],
    errors: Sequence[str],
    previous_texts: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, str]:
    """修复只重写失败槽位；通过槽位原样保留。"""
    failed = set(failed_slots)
    if not failed:
        raise ValueError("没有失败槽位，不需要修复")

    system, _ = build_generation_messages(
        plan, contexts, previous_texts=previous_texts
    )
    system += (
        "\n\n这是一次修复：只重写失败槽位，其他槽位不要输出；"
        "不得改变槽位、概念或题型。"
    )

    kept = [
        {
            "slot": draft.slot,
            "concept_id": draft.concept_id,
            "question_type": draft.question_type,
            "question_text": draft.question_text,
        }
        for draft in drafts
        if draft.slot not in failed
    ]
    failed_lines = [f"- 槽位 {slot}" for slot in sorted(failed)]
    error_lines = [f"- {error}" for error in errors]
    user = "\n\n".join(
        [
            _concept_blocks(plan, contexts, previous_texts or {}),
            _slot_table(plan),
            "## 已通过槽位（保持原样，不要重复输出）\n"
            + (json.dumps(kept, ensure_ascii=False, indent=2) if kept else "（无）"),
            "## 失败槽位\n" + "\n".join(failed_lines),
            "## 失败原因\n" + "\n".join(error_lines),
            _output_schema().replace(
                "questions 必须恰好 5 条，slot 为 1-5 各一条。",
                "只输出失败槽位，slot 必须与失败槽位一一对应。",
            ),
        ]
    )
    return system, user


def parse_generation(
    raw: str,
    plan: SessionPlan,
    *,
    slots: Sequence[int] | None = None,
) -> tuple[QuestionDraft, ...]:
    """解析模型输出。``slots`` 给定时只接受这些槽位（修复调用）。"""
    try:
        payload = extract_json_object(raw)
    except ScoringError as exc:
        raise GenerationError(f"出题输出无法解析：{exc}") from exc

    items = payload.get("questions")
    if not isinstance(items, list) or not items:
        raise GenerationError("出题输出缺少 questions 列表")

    drafts: list[QuestionDraft] = []
    for item in items:
        if not isinstance(item, dict):
            raise GenerationError("questions 里有非对象元素")
        slot = _as_int(item.get("slot"), "slot", "?")
        concept_id = _as_text(item.get("concept_id"), "concept_id", slot)
        question_type = _as_text(item.get("question_type"), "question_type", slot)
        drafts.append(
            QuestionDraft(
                slot=slot,
                concept_id=concept_id,
                question_type=question_type,
                question_text=_as_text(
                    item.get("question_text"), "question_text", slot
                ),
                reference_answer=_as_text(
                    item.get("reference_answer"), "reference_answer", slot
                ),
                must_have=_as_text_list(item.get("must_have"), "must_have", slot),
                red_flags=_as_text_list(item.get("red_flags"), "red_flags", slot),
                source_ref=_as_int(item.get("source_ref"), "source_ref", slot),
                source_excerpt=_as_text(
                    item.get("source_excerpt"), "source_excerpt", slot
                ),
            )
        )

    got = [draft.slot for draft in drafts]
    if len(got) != len(set(got)):
        raise GenerationError(f"出题槽位重复：{got}")
    expected = set(range(1, 6)) if slots is None else set(slots)
    if set(got) != expected:
        raise GenerationError(
            f"出题槽位不完整：期望 {sorted(expected)}，实际 {sorted(got)}"
        )
    return tuple(sorted(drafts, key=lambda draft: draft.slot))


def _as_text(value: Any, field: str, slot: int) -> str:
    if not isinstance(value, str):
        raise GenerationError(f"槽位 {slot} 的 {field} 不是字符串：{value!r}")
    return value.strip()


def _as_text_list(value: Any, field: str, slot: int) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise GenerationError(f"槽位 {slot} 的 {field} 不是字符串列表")
    return tuple(item.strip() for item in value)


def _as_int(value: Any, field: str, slot: int | str) -> int:
    if isinstance(value, bool):
        raise GenerationError(f"槽位 {slot} 的 {field} 不是整数：{value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise GenerationError(f"槽位 {slot} 的 {field} 不是整数：{value!r}")


def validate_question_set(
    drafts: Sequence[QuestionDraft],
    contexts: Mapping[str, GenerationContext],
    plan: SessionPlan,
    *,
    previous_texts: Mapping[str, Sequence[str]] | None = None,
) -> ValidationResult:
    """硬失败进修复；软警告只进修复提示词，不改变 ok。"""
    errors: list[str] = []
    warnings: list[str] = []
    failed: set[int] = set()

    planned = {slot.slot: slot for slot in plan.slots}
    got = [draft.slot for draft in drafts]
    if len(drafts) != len(planned) or set(got) != set(planned):
        return ValidationResult(
            ok=False,
            errors=(f"槽位不完整：期望 {sorted(planned)}，实际 {sorted(got)}",),
            failed_slots=tuple(sorted(planned)),
        )

    for draft in drafts:
        slot = planned[draft.slot]
        _check_draft(draft, slot, previous_texts or {}, warnings)
        if draft.concept_id != slot.concept_id:
            errors.append(
                f"槽位 {draft.slot}：概念应为 {slot.concept_id}，实际 {draft.concept_id}"
            )
            failed.add(draft.slot)
        if draft.question_type != slot.question_type:
            errors.append(
                f"槽位 {draft.slot}：题型应为 {slot.question_type}，"
                f"实际 {draft.question_type}"
            )
            failed.add(draft.slot)
        text = draft.question_text.strip()
        if not text:
            errors.append(f"槽位 {draft.slot}：题干为空")
            failed.add(draft.slot)
        elif len(text) > QUESTION_MAX_CHARS:
            errors.append(f"槽位 {draft.slot}：题干超过 {QUESTION_MAX_CHARS} 字")
            failed.add(draft.slot)
        if _has_code_word(text):
            errors.append(f"槽位 {draft.slot}：题干含代码实现禁词")
            failed.add(draft.slot)
        if not draft.reference_answer.strip():
            errors.append(f"槽位 {draft.slot}：缺少参考答案")
            failed.add(draft.slot)
        if not MUST_HAVE_MIN <= len(draft.must_have) <= MUST_HAVE_MAX:
            errors.append(
                f"槽位 {draft.slot}：must_have 需要 {MUST_HAVE_MIN}-{MUST_HAVE_MAX} 条"
            )
            failed.add(draft.slot)
        elif any(not item for item in draft.must_have):
            errors.append(f"槽位 {draft.slot}：must_have 有空条目")
            failed.add(draft.slot)
        if not RED_FLAGS_MIN <= len(draft.red_flags) <= RED_FLAGS_MAX:
            errors.append(
                f"槽位 {draft.slot}：red_flags 需要 {RED_FLAGS_MIN}-{RED_FLAGS_MAX} 条"
            )
            failed.add(draft.slot)
        elif any(not item for item in draft.red_flags):
            errors.append(f"槽位 {draft.slot}：red_flags 有空条目")
            failed.add(draft.slot)

        context = contexts.get(slot.concept_id)
        chunk = _find_chunk(context, draft.source_ref)
        if context is None:
            errors.append(f"槽位 {draft.slot}：概念缺少上下文 {slot.concept_id}")
            failed.add(draft.slot)
        elif chunk is None:
            errors.append(f"槽位 {draft.slot}：source_ref {draft.source_ref} 越界")
            failed.add(draft.slot)
        elif draft.source_excerpt.strip() not in chunk.text:
            errors.append(f"槽位 {draft.slot}：source_excerpt 不是原文逐字子串")
            failed.add(draft.slot)

        rubric = build_rubric(
            question_type=draft.question_type,
            must_have=draft.must_have,
            red_flags=draft.red_flags,
            reference_answer=draft.reference_answer,
        )
        if [level["score"] for level in rubric["levels"]] != list(RUBRIC_SCORES):
            errors.append(f"槽位 {draft.slot}：五档 rubric 不是 0/40/70/90/100")
            failed.add(draft.slot)

    seen: dict[str, int] = {}
    for draft in drafts:
        normalized = _normalize_text(draft.question_text)
        if not normalized:
            continue
        if normalized in seen:
            errors.append(
                f"槽位 {draft.slot}：题干与槽位 {seen[normalized]} 重复"
            )
            failed.add(draft.slot)
        else:
            seen[normalized] = draft.slot

    return ValidationResult(
        ok=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        failed_slots=tuple(sorted(failed)),
    )


def _check_draft(
    draft: QuestionDraft,
    slot: Slot,
    previous_texts: Mapping[str, Sequence[str]],
    warnings: list[str],
) -> None:
    text = draft.question_text.strip()
    label = QUESTION_TYPE_LABELS.get(slot.question_type, slot.question_type)

    if slot.question_type == "concept" and re.search(
        r"什么是|的定义|定义是|是什么意思", text
    ):
        warnings.append(f"槽位 {draft.slot}：概念题像定义题，缺少因果或业务后果")

    if slot.question_type == "business":
        if not any(marker in text for marker in _SCENARIO_MARKERS):
            warnings.append(f"槽位 {draft.slot}：业务运用题缺少具体业务场景")
        if not any(marker in text for marker in _JUDGMENT_MARKERS):
            warnings.append(f"槽位 {draft.slot}：业务运用题缺少具体动作或有效判断")

    if slot.question_type == "tradeoff" and not any(
        marker in text for marker in _TRADEOFF_MARKERS
    ):
        warnings.append(f"槽位 {draft.slot}：取舍题缺少选择、代价或反转条件")

    if slot.question_type == "cost_risk":
        if not any(marker in text for marker in _COST_RISK_MARKERS):
            warnings.append(f"槽位 {draft.slot}：成本风险题缺少成本或风险要素")
        if not any(marker in text for marker in _FALLBACK_MARKERS):
            warnings.append(f"槽位 {draft.slot}：成本风险题缺少承担者或兜底")

    if slot.question_type == "synthesis" and not any(
        marker in text for marker in _SYNTHESIS_MARKERS
    ):
        warnings.append(f"槽位 {draft.slot}：综合题缺少决策、依据或边界")

    excerpt = draft.source_excerpt.strip()
    if len(excerpt) < EXCERPT_MIN_CHARS:
        warnings.append(f"槽位 {draft.slot}：source_excerpt 过短，像标题或单词")

    joined = " ".join(draft.must_have)
    required = _TYPE_REQUIRED_WORDS.get(slot.question_type)
    if required and not any(word in joined for word in required):
        warnings.append(f"槽位 {draft.slot}：must_have 与题型 {label} 不匹配")
    if slot.question_type == "concept" and draft.must_have and all(
        "定义" in item or "含义" in item for item in draft.must_have
    ):
        warnings.append(f"槽位 {draft.slot}：must_have 只考定义，与概念理解不匹配")

    if any(
        _similarity(text, previous) >= 0.8
        for previous in previous_texts.get(slot.concept_id, ())
    ):
        warnings.append(f"槽位 {draft.slot}：题干与上一场同概念题目高度相似")


def _find_chunk(
    context: GenerationContext | None, ref: int
) -> ContextChunk | None:
    if context is None:
        return None
    for chunk in context.chunks:
        if chunk.ref == ref:
            return chunk
    return None


def _has_code_word(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in CODE_IMPLEMENTATION_WORDS)


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _similarity(left: str, right: str) -> float:
    a = _normalize_text(left)
    b = _normalize_text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    grams_a = {a[index : index + 2] for index in range(len(a) - 1)} or {a}
    grams_b = {b[index : index + 2] for index in range(len(b) - 1)} or {b}
    return len(grams_a & grams_b) / len(grams_a | grams_b)


def to_generated_question(
    draft: QuestionDraft, context_chunk: ContextChunk
) -> GeneratedQuestion:
    return GeneratedQuestion(
        slot=draft.slot,
        concept_id=draft.concept_id,
        question_type=draft.question_type,
        question_text=draft.question_text.strip(),
        reference_answer=draft.reference_answer.strip(),
        rubric=build_rubric(
            question_type=draft.question_type,
            must_have=draft.must_have,
            red_flags=draft.red_flags,
            reference_answer=draft.reference_answer.strip(),
        ),
        source_chunk_id=context_chunk.chunk_id,
        source_url=context_chunk.source_url,
        source_excerpt=draft.source_excerpt.strip(),
    )


def apply_repair(
    original: Sequence[QuestionDraft],
    repaired: Sequence[QuestionDraft],
    *,
    failed_slots: Sequence[int],
    contexts: Mapping[str, GenerationContext],
    plan: SessionPlan,
    previous_texts: Mapping[str, Sequence[str]] | None = None,
) -> tuple[QuestionDraft, ...]:
    """合并修复结果并复验；仍不合法则抛 ``GenerationError``。"""
    failed = set(failed_slots)
    by_slot = {draft.slot: draft for draft in repaired}
    if set(by_slot) != failed:
        raise GenerationError(
            f"修复槽位不匹配：期望 {sorted(failed)}，实际 {sorted(by_slot)}"
        )

    merged = {draft.slot: draft for draft in original}
    merged.update(by_slot)
    ordered = tuple(merged[slot.slot] for slot in plan.slots)
    result = validate_question_set(
        ordered, contexts, plan, previous_texts=previous_texts
    )
    if not result.ok:
        raise GenerationError("修复后仍不合法：" + "；".join(result.errors))
    return ordered
