"""每个 agent 回合的工单：程序给定当前步骤能看见什么、能用哪些工具。

只做数据整理；不调模型、不查库、不写库。StepBrief 在回合内不可变。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .agent_tools import AGENT_STEPS, ToolBudget
from .concepts import Concept
from .ports import AgentMessage


@dataclass(frozen=True, slots=True)
class StepBrief:
    step: str
    today: str
    budget: ToolBudget
    progress: Mapping[str, Any] = field(default_factory=dict)
    session: Mapping[str, Any] | None = None
    question: Mapping[str, Any] | None = None
    last_scored: Mapping[str, Any] | None = None
    concept: Mapping[str, Any] | None = None
    history: tuple[AgentMessage, ...] = ()
    tone_hint: str = ""
    memory_context: str = ""
    policy: Mapping[str, bool] = field(
        default_factory=lambda: {
            "can_search_materials": True,
            "can_search_web": True,
            "can_score": False,
            "can_advance": False,
            "can_reveal_answer": False,
        }
    )

    def __post_init__(self) -> None:
        if self.step not in AGENT_STEPS:
            raise ValueError(f"未知的 agent 步骤：{self.step}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "today": self.today,
            "session": dict(self.session) if self.session is not None else None,
            "question": dict(self.question) if self.question is not None else None,
            "last_scored": (
                dict(self.last_scored) if self.last_scored is not None else None
            ),
            "concept": dict(self.concept) if self.concept is not None else None,
            "progress": dict(self.progress),
            "budget": self.budget.as_dict(),
            "policy": dict(self.policy),
        }


def _options(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, (dict, list)) else None
    return None


def question_payload(question: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """当前题只给作答所需字段；rubric/答案键/参考答案一律不带。"""
    if not question:
        return None
    return {
        "id": question.get("id"),
        "text": question.get("question_text") or question.get("text") or "",
        "type": question.get("question_type"),
        "options": _options(question.get("options_json")),
    }


def last_scored_payload(question: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """上一道已评分题：题干、用户回答、分数、why 与出处；不含 rubric。"""
    if not question or question.get("score") is None:
        return None
    return {
        "question_id": question.get("id"),
        "text": question.get("question_text") or question.get("text") or "",
        "answer_text": question.get("answer_text") or "",
        "score": question.get("score"),
        "why": question.get("feedback") or "",
        "type": question.get("question_type"),
        "source_url": question.get("source_url"),
        "source_excerpt": question.get("source_excerpt"),
    }


def concept_payload(concept: Concept | None) -> dict[str, Any] | None:
    if concept is None:
        return None
    return {
        "id": concept.id,
        "name": concept.name,
        "aliases": list(concept.aliases),
        "plain_def": concept.plain_def,
        "difficulty": concept.difficulty,
        "prerequisites": list(concept.prerequisites),
        "source_url": concept.source.url,
        "source_excerpt": concept.source.excerpt,
    }


def session_payload(
    session_id: str,
    kind: str,
    question_index: int,
    total: int,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "kind": kind,
        "question_index": question_index,
        "total": total,
    }


def build_free_talk_brief(
    *,
    today: str,
    progress: Mapping[str, Any] | None = None,
    history: Sequence[AgentMessage] = (),
    budget: ToolBudget | None = None,
    tone_hint: str = "",
    memory_context: str = "",
) -> StepBrief:
    return StepBrief(
        step="free_talk",
        today=today,
        budget=budget or ToolBudget(),
        progress=dict(progress or {}),
        history=tuple(history),
        tone_hint=tone_hint,
        memory_context=memory_context,
    )


def _build_session_brief(
    *,
    step: str,
    today: str,
    session: Mapping[str, Any],
    question: Mapping[str, Any] | None,
    concept: Concept | None,
    last_scored: Mapping[str, Any] | None = None,
    progress: Mapping[str, Any] | None = None,
    history: Sequence[AgentMessage] = (),
    budget: ToolBudget | None = None,
    tone_hint: str = "",
    memory_context: str = "",
) -> StepBrief:
    if not question:
        raise ValueError(f"{step} 需要当前题")
    return StepBrief(
        step=step,
        today=today,
        budget=budget or ToolBudget(),
        progress=dict(progress or {}),
        session=dict(session),
        question=question_payload(question),
        last_scored=last_scored_payload(last_scored),
        concept=concept_payload(concept),
        history=tuple(history),
        tone_hint=tone_hint,
        memory_context=memory_context,
    )


def build_teach_brief(
    *,
    today: str,
    session: Mapping[str, Any],
    question: Mapping[str, Any] | None,
    concept: Concept | None,
    last_scored: Mapping[str, Any] | None = None,
    progress: Mapping[str, Any] | None = None,
    history: Sequence[AgentMessage] = (),
    budget: ToolBudget | None = None,
    tone_hint: str = "",
    memory_context: str = "",
) -> StepBrief:
    return _build_session_brief(
        step="teach",
        today=today,
        session=session,
        question=question,
        concept=concept,
        last_scored=last_scored,
        progress=progress,
        history=history,
        budget=budget,
        tone_hint=tone_hint,
        memory_context=memory_context,
    )


def build_clarify_brief(
    *,
    today: str,
    session: Mapping[str, Any],
    question: Mapping[str, Any] | None,
    concept: Concept | None,
    last_scored: Mapping[str, Any] | None = None,
    progress: Mapping[str, Any] | None = None,
    history: Sequence[AgentMessage] = (),
    budget: ToolBudget | None = None,
    tone_hint: str = "",
    memory_context: str = "",
) -> StepBrief:
    return _build_session_brief(
        step="clarify",
        today=today,
        session=session,
        question=question,
        concept=concept,
        last_scored=last_scored,
        progress=progress,
        history=history,
        budget=budget,
        tone_hint=tone_hint,
        memory_context=memory_context,
    )
