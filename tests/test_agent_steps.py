from __future__ import annotations

import pytest

from core.agent_steps import (
    StepBrief,
    build_clarify_brief,
    build_free_talk_brief,
    build_teach_brief,
    concept_payload,
    last_scored_payload,
    question_payload,
)
from core.agent_tools import ToolBudget
from core.concepts import load_concepts
from core.ports import AgentMessage
from tests.support import CONCEPTS_PATH


def test_free_talk_brief_shape() -> None:
    history = (AgentMessage(role="user", content="什么是 Agent 循环？"),)
    brief = build_free_talk_brief(
        today="2026-11-25",
        progress={"active": [{"id": "agent-loop", "mastery": 2}], "recent": []},
        history=history,
    )
    assert brief.step == "free_talk"
    assert brief.today == "2026-11-25"
    assert brief.session is None
    assert brief.question is None
    assert brief.last_scored is None
    assert brief.concept is None
    assert brief.history == history
    assert brief.budget == ToolBudget()
    assert brief.policy["can_score"] is False
    assert brief.policy["can_advance"] is False

    payload = brief.as_dict()
    assert payload["step"] == "free_talk"
    assert payload["session"] is None
    assert payload["question"] is None
    assert payload["progress"] == {
        "active": [{"id": "agent-loop", "mastery": 2}],
        "recent": [],
    }
    assert payload["budget"]["max_tool_calls"] == 8
    assert payload["budget"]["max_calls_per_tool"] == 4
    assert payload["budget"]["max_web_calls"] == 4
    assert payload["budget"]["deadline_seconds"] == 60.0
    assert "history" not in payload
    assert "rubric_json" not in payload
    assert "answer_key" not in payload


def test_step_brief_rejects_non_agent_step() -> None:
    with pytest.raises(ValueError):
        StepBrief(step="answer", today="2026-11-25", budget=ToolBudget())


def test_question_payload_strips_rubric_and_answer_key() -> None:
    payload = question_payload(
        {
            "id": 7,
            "question_text": "这题怎么选？",
            "question_type": "tradeoff",
            "options_json": '["A", "B"]',
            "rubric_json": '{"reference_answer": "secret"}',
            "answer_key": "A",
        }
    )
    assert payload == {
        "id": 7,
        "text": "这题怎么选？",
        "type": "tradeoff",
        "options": ["A", "B"],
    }


def test_question_payload_ignores_future_questions() -> None:
    payload = question_payload(
        {
            "id": 7,
            "question_text": "当前题",
            "future_questions": ["未来题秘密"],
            "next_question_text": "下一题秘密",
        }
    )
    assert payload is not None
    assert "future_questions" not in payload
    assert "下一题秘密" not in str(payload)
    assert "未来题秘密" not in str(payload)


def test_last_scored_payload() -> None:
    assert last_scored_payload({"id": 1, "score": None}) is None
    payload = last_scored_payload(
        {
            "id": 3,
            "question_text": "上一题",
            "answer_text": "我的回答",
            "score": 60,
            "feedback": "方向对但缺例子",
            "question_type": "business",
            "source_url": "fixture://x",
            "source_excerpt": "出处",
            "rubric_json": '{"reference_answer": "secret"}',
        }
    )
    assert payload == {
        "question_id": 3,
        "text": "上一题",
        "answer_text": "我的回答",
        "score": 60,
        "why": "方向对但缺例子",
        "type": "business",
        "source_url": "fixture://x",
        "source_excerpt": "出处",
    }


def test_concept_payload() -> None:
    concept = load_concepts(CONCEPTS_PATH)[0]
    payload = concept_payload(concept)
    assert payload is not None
    assert payload["id"] == concept.id
    assert payload["plain_def"] == concept.plain_def
    assert payload["source_url"] == concept.source.url
    assert concept_payload(None) is None


def _session() -> dict:
    return {
        "session_id": "s1",
        "kind": "daily",
        "question_index": 3,
        "total": 5,
    }


def _question() -> dict:
    return {
        "id": 3,
        "question_text": "当前题",
        "question_type": "business",
        "options_json": None,
        "rubric_json": '{"reference_answer": "secret"}',
        "answer_key": "A",
        "source_url": "fixture://current",
        "source_excerpt": "当前题出处",
    }


def test_teach_brief_has_current_and_last_scored_without_rubric() -> None:
    concept = load_concepts(CONCEPTS_PATH)[0]
    brief = build_teach_brief(
        today="2026-11-25",
        session=_session(),
        question=_question(),
        concept=concept,
        last_scored={
            "id": 2,
            "question_text": "上一题",
            "answer_text": "我的回答",
            "score": 60,
            "feedback": "缺例子",
            "question_type": "concept",
            "source_url": "fixture://last",
            "source_excerpt": "上一题出处",
            "rubric_json": '{"reference_answer": "secret"}',
        },
        progress={"active": [], "recent": []},
        history=(AgentMessage(role="user", content="讲讲这题"),),
    )
    assert brief.step == "teach"
    assert brief.session == _session()
    assert brief.question == {
        "id": 3,
        "text": "当前题",
        "type": "business",
        "options": None,
    }
    assert brief.last_scored is not None
    assert brief.last_scored["score"] == 60
    assert brief.last_scored["answer_text"] == "我的回答"
    assert "rubric_json" not in brief.last_scored
    assert brief.concept is not None
    assert brief.concept["id"] == concept.id
    assert brief.policy["can_score"] is False
    assert "rubric_json" not in str(brief.as_dict())
    assert "answer_key" not in str(brief.as_dict())


def test_clarify_brief_shape() -> None:
    concept = load_concepts(CONCEPTS_PATH)[0]
    brief = build_clarify_brief(
        today="2026-11-25",
        session=_session(),
        question=_question(),
        concept=concept,
    )
    assert brief.step == "clarify"
    assert brief.last_scored is None
    assert brief.question is not None
    assert brief.question["text"] == "当前题"


def test_teach_and_clarify_brief_carry_tone_hint() -> None:
    concept = load_concepts(CONCEPTS_PATH)[0]
    for builder in (build_teach_brief, build_clarify_brief):
        brief = builder(
            today="2026-11-25",
            session=_session(),
            question=_question(),
            concept=concept,
            tone_hint="TONE",
        )
        assert brief.tone_hint == "TONE"


def test_session_brief_requires_question() -> None:
    concept = load_concepts(CONCEPTS_PATH)[0]
    with pytest.raises(ValueError):
        build_teach_brief(
            today="2026-11-25",
            session=_session(),
            question=None,
            concept=concept,
        )
    with pytest.raises(ValueError):
        build_clarify_brief(
            today="2026-11-25",
            session=_session(),
            question=None,
            concept=concept,
        )
