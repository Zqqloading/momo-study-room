from __future__ import annotations

import json

import pytest

from core.scoring import (
    SCORE_SYSTEM_PROMPT,
    ScoringError,
    build_score_messages,
    extract_json_object,
    parse_score_result,
)

VALID = """{"questions":[{"id":"q1","score":70,"why":"方向对但含糊",
"misconception_hit":false,"certain":true}],"session_misconception":null}"""


def test_parses_valid_contract() -> None:
    result = parse_score_result(VALID, expected_ids=["q1"])
    assert len(result.questions) == 1
    assert result.questions[0].score == 70
    assert result.questions[0].certain is True
    assert result.session_misconception is None


def test_tolerates_json_fence_and_chatter() -> None:
    raw = "好的，结果如下：\n```json\n" + VALID + "\n```\n希望有帮助。"
    result = parse_score_result(raw, expected_ids=["q1"])
    assert result.questions[0].score == 70


def test_parses_session_misconception() -> None:
    raw = VALID.replace(
        "null", '{"text":"把 workflow 当成 agent","concept_key":"agent"}'
    )
    result = parse_score_result(raw, expected_ids=["q1"])
    assert result.session_misconception is not None
    assert result.session_misconception.concept_key == "agent"


@pytest.mark.parametrize("score", [-1, 101, 70.5, "70", True])
def test_rejects_bad_scores(score: object) -> None:
    raw = VALID.replace('"score":70', f'"score":{json.dumps(score)}')
    with pytest.raises(ScoringError):
        parse_score_result(raw)


def test_rejects_missing_why() -> None:
    raw = '{"questions":[{"id":"q1","score":70}],"session_misconception":null}'
    with pytest.raises(ScoringError):
        parse_score_result(raw)


def test_rejects_duplicate_ids() -> None:
    raw = (
        '{"questions":[{"id":"q1","score":70,"why":"a"},'
        '{"id":"q1","score":80,"why":"b"}],"session_misconception":null}'
    )
    with pytest.raises(ScoringError):
        parse_score_result(raw)


def test_rejects_missing_expected_question() -> None:
    with pytest.raises(ScoringError, match="漏评分题"):
        parse_score_result(VALID, expected_ids=["q1", "q2"])


def test_rejects_unknown_extra_question() -> None:
    with pytest.raises(ScoringError, match="多出未知题"):
        parse_score_result(VALID, expected_ids=[])


def test_accepts_string_booleans() -> None:
    raw = VALID.replace('"certain":true', '"certain":"false"')
    result = parse_score_result(raw)
    assert result.questions[0].certain is False


@pytest.mark.parametrize("bad", ["yes", 2, None])
def test_rejects_non_boolean_flags(bad: object) -> None:
    raw = VALID.replace('"certain":true', f'"certain":{json.dumps(bad)}')
    with pytest.raises(ScoringError, match="certain"):
        parse_score_result(raw)


def test_extract_returns_top_level_object() -> None:
    assert extract_json_object('前言 {"a": 1} 后记') == {"a": 1}


def test_parses_reference_answer() -> None:
    raw = VALID.replace(
        '"misconception_hit"', '"reference_answer":"观察、决策、行动，直到目标完成", "misconception_hit"'
    )
    result = parse_score_result(raw, expected_ids=["q1"])
    assert result.questions[0].reference_answer.startswith("观察")


def test_missing_reference_answer_is_empty() -> None:
    result = parse_score_result(VALID)
    assert result.questions[0].reference_answer == ""


@pytest.mark.parametrize("bad", [1, [], {}])
def test_rejects_non_string_reference_answer(bad: object) -> None:
    raw = VALID.replace(
        '"misconception_hit"',
        f'"reference_answer":{json.dumps(bad)}, "misconception_hit"',
    )
    with pytest.raises(ScoringError, match="reference_answer"):
        parse_score_result(raw)


def test_extract_rejects_non_json() -> None:
    with pytest.raises(ScoringError):
        extract_json_object("完全不是 JSON")


def test_build_score_messages_includes_type_excerpt_and_reference() -> None:
    question = {
        "id": 7,
        "question_text": "客户预算有限时你会怎么选？",
        "question_type": "tradeoff",
        "source_excerpt": "MVP 先把验证范围压到核心流程。",
        "rubric_json": json.dumps(
            {
                "must_have": ["说清选择"],
                "reference_answer": "选 B，放弃短期速度。",
            },
            ensure_ascii=False,
        ),
    }

    system, user = build_score_messages(question, "我选 B")

    assert "题目类型：tradeoff（取舍权衡）" in user
    assert "材料出处：MVP 先把验证范围压到核心流程。" in user
    assert "参考答案：选 B，放弃短期速度。" in user
    assert "取舍权衡：没有明确选择、代价或反转条件：最高 69。" in system


def test_build_score_messages_falls_back_to_rubric_criteria() -> None:
    question = {
        "id": 8,
        "question_text": "旧题库开放题",
        "rubric_json": json.dumps({"criteria": "观察后再行动"}, ensure_ascii=False),
    }

    _, user = build_score_messages(question, "我的回答")

    assert "题目类型" not in user
    assert "参考答案：观察后再行动" in user


@pytest.mark.parametrize(
    "marker",
    [
        "只背定义、只复述材料原句",
        "业务运用：没有具体动作或场景映射",
        "取舍权衡：没有明确选择、代价或反转条件",
        "成本风险：少于 2 项成本或风险",
        "综合判断：没有决策、依据或边界",
    ],
)
def test_system_prompt_covers_all_type_caps(marker: str) -> None:
    assert marker in SCORE_SYSTEM_PROMPT


@pytest.mark.parametrize(
    "bad", ['"把 workflow 当成 agent"', '["把 workflow 当成 agent"]']
)
def test_rejects_non_object_session_misconception(bad: str) -> None:
    raw = VALID.replace("null", bad)
    with pytest.raises(ScoringError, match="session_misconception"):
        parse_score_result(raw)
