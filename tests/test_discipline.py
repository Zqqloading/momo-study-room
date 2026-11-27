from __future__ import annotations

from core.discipline import D1, D2, D3, D4, D5, discipline_block, rules_for
from core.scoring import SCORE_SYSTEM_PROMPT


def test_surface_rule_mapping() -> None:
    assert rules_for("free_talk") == ("D1", "D2")
    assert rules_for("teach") == ("D1", "D2", "D5")
    assert rules_for("clarify") == ("D1", "D2", "D5")
    assert rules_for("scoring") == ("D3",)
    assert rules_for("question_generation") == ("D2", "D4")
    assert rules_for("extraction") == ("D2",)
    assert rules_for("unknown") == ()


def test_conversational_blocks() -> None:
    free = discipline_block("free_talk")
    assert D1 in free and D2 in free
    assert D5 not in free

    teach = discipline_block("teach")
    assert D1 in teach and D2 in teach and D5 in teach
    assert "【底线" in teach


def test_scoring_prompt_has_feedback_tone_line() -> None:
    assert "反馈只评价答案，不评价用户本人" in SCORE_SYSTEM_PROMPT
    assert "不讽刺、不贬低" in SCORE_SYSTEM_PROMPT
    assert "只背定义、只复述材料原句" in SCORE_SYSTEM_PROMPT


def test_rules_are_the_expected_texts() -> None:
    assert "不会就说不会" in D1
    assert "不编造引用" in D2
    assert "评分不注水" in D3
    assert "题目数量严格按规范" in D4
    assert "不主动替用户答题" in D5
