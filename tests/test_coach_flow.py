from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from core.coach import NoSessionAvailable, clip_sentence
from core.question_generation import QUESTION_TYPES
from support import (
    BANK_PATH,
    FailingQuestionGenerator,
    FakeQuestionGenerator,
    ScriptedScorer,
    make_coach,
)


def test_discriminate_is_scored_locally() -> None:
    scorer = ScriptedScorer()
    store, coach, _ = make_coach(scorer=scorer)
    try:
        started = asyncio.run(coach.start())
        question = next(
            item for item in started.questions if item.kind == "discriminate"
        )

        result = asyncio.run(
            coach.answer(started.session_id, question.id, "C")
        )
        assert result.score == 100
        assert result.why == "答对了"
        assert result.speak is False
        assert scorer.calls == 0

        row = store.question(question.id)
        assert row is not None
        assert row["score"] == 100
    finally:
        store.close()


def test_discriminate_wrong_choice_scores_40_with_explanation() -> None:
    store, coach, _ = make_coach()
    try:
        started = asyncio.run(coach.start())
        question = next(
            item for item in started.questions if item.kind == "discriminate"
        )
        result = asyncio.run(coach.answer(started.session_id, question.id, "A"))
        assert result.score == 40
        assert "正确答案是 C" in result.why
        assert "解析" in result.why
        assert "改变外部状态" in result.why
        assert result.speak is True
    finally:
        store.close()


def test_open_question_uses_scorer_and_commits() -> None:
    store, coach, _ = make_coach()
    try:
        started = asyncio.run(coach.start())
        question = started.questions[0]
        result = asyncio.run(
            coach.answer(started.session_id, question.id, "观察、决策、行动")
        )
        assert result.score == 70
        assert "参考答案" in result.why
        row = store.question(question.id)
        assert row is not None
        assert row["score"] == 70
        assert row["answer_text"] == "观察、决策、行动"
        agent = store.agent_session(started.session_id)
        assert agent is not None
        assert agent["last_question_id"] == question.id
    finally:
        store.close()


def test_open_question_retries_once_then_succeeds() -> None:
    scorer = ScriptedScorer([ValueError("bad json")])
    store, coach, _ = make_coach(scorer=scorer)
    try:
        started = asyncio.run(coach.start())
        question = started.questions[0]
        result = asyncio.run(coach.answer(started.session_id, question.id, "答案"))
        assert result.score == 70
        assert scorer.calls == 2
    finally:
        store.close()


def test_open_question_two_failures_leave_unscored_and_continue() -> None:
    scorer = ScriptedScorer([ValueError("bad"), ValueError("bad")])
    store, coach, _ = make_coach(scorer=scorer)
    try:
        started = asyncio.run(coach.start())
        question = started.questions[0]
        result = asyncio.run(coach.answer(started.session_id, question.id, "答案"))
        assert result.score is None
        assert result.why == "本题未评分"
        assert scorer.calls == 2

        row = store.question(question.id)
        assert row is not None
        assert row["score"] is None
        assert row["feedback"] == "本题未评分"

        next_question = started.questions[1]
        second = asyncio.run(
            coach.answer(started.session_id, next_question.id, "第二题")
        )
        assert second.score == 70
    finally:
        store.close()


def test_open_question_feedback_includes_reference_answer() -> None:
    scorer = ScriptedScorer(reference_answer="观察、决策、行动，循环直到目标完成。")
    store, coach, _ = make_coach(scorer=scorer)
    try:
        started = asyncio.run(coach.start())
        question = started.questions[0]
        result = asyncio.run(coach.answer(started.session_id, question.id, "我的回答"))
        assert "参考答案" in result.why
        assert "观察、决策、行动" in result.why
    finally:
        store.close()


def test_unknown_returns_zero_and_short_definition() -> None:
    scorer = ScriptedScorer()
    store, coach, _ = make_coach(scorer=scorer)
    try:
        started = asyncio.run(coach.start())
        question = started.questions[0]
        result = coach.mark_unknown(started.session_id, question.id)
        assert result.score == 0
        assert len(result.why) <= 60
        assert "例：" in result.why
        assert scorer.calls == 0
    finally:
        store.close()


def test_start_uses_generated_questions_and_persists_provenance() -> None:
    generator = FakeQuestionGenerator()
    store, coach, _ = make_coach(generator=generator)
    try:
        started = asyncio.run(coach.start())

        assert generator.calls == 1
        assert started.intro == "今天从「Agent 循环」开始。"
        assert started.focus is not None
        assert started.focus.concept_id == "agent-loop"
        assert started.focus.reason_kind == "no_signal"
        assert [q.question_type for q in started.questions] == list(QUESTION_TYPES)
        assert [q.kind for q in started.questions] == [
            "recall",
            "apply",
            "apply",
            "apply",
            "apply",
        ]
        rows = store.session_questions(started.session_id)
        assert [row["question_type"] for row in rows] == list(QUESTION_TYPES)
        assert all(row["question_bank_id"] is None for row in rows)
        assert all(row["source_chunk_id"] for row in rows)
        assert all(
            json.loads(row["generation_meta_json"])["origin"] == "generated"
            for row in rows
        )
        meta = json.loads(rows[0]["generation_meta_json"])
        assert meta["model"] == "fake-qgen"
        assert meta["prompt_version"] == "qgen-v1"
        assert meta["repair_count"] == 0
        assert meta["validation"] == "passed"
        assert isinstance(meta["retrieved_chunk_ids"], list)
    finally:
        store.close()


def test_generation_failure_falls_back_whole_session() -> None:
    generator = FailingQuestionGenerator("模型超时")
    store, coach, _ = make_coach(generator=generator)
    try:
        started = asyncio.run(coach.start())

        assert generator.calls == 1
        assert len(started.questions) == 5
        assert all(q.question_type is None for q in started.questions)
        rows = store.session_questions(started.session_id)
        assert len(rows) == 5
        assert all(row["question_bank_id"] for row in rows)
        assert all(row["question_type"] is None for row in rows)
        assert all(
            json.loads(row["generation_meta_json"])["origin"] == "fallback"
            for row in rows
        )
        assert "模型超时" in json.loads(rows[0]["generation_meta_json"])["reason"]
    finally:
        store.close()


def test_fallback_insufficient_bank_raises_no_session() -> None:
    store, coach, _ = make_coach(generator=FailingQuestionGenerator())
    try:
        rows = json.loads(Path(BANK_PATH).read_text(encoding="utf-8"))
        agent_loop = [row for row in rows if row["concept_id"] == "agent-loop"]
        others = [row for row in rows if row["concept_id"] != "agent-loop"]
        store.import_question_bank(others + agent_loop[:4])

        with pytest.raises(NoSessionAvailable):
            asyncio.run(coach.start())
    finally:
        store.close()


def test_answer_and_settlement_carry_type_and_source() -> None:
    store, coach, _ = make_coach(generator=FakeQuestionGenerator())
    try:
        started = asyncio.run(coach.start())
        for question in started.questions:
            answer = asyncio.run(
                coach.answer(started.session_id, question.id, "我的回答")
            )
            assert answer.question_type == question.question_type
            assert answer.source_url == "fixture://agent-loop"
            assert answer.source_excerpt == "agent-loop 的出处摘录"

        settlement = coach.finish(started.session_id)
        assert settlement.scores[0].question_type == "concept"
        assert settlement.scores[0].source_url == "fixture://agent-loop"
        assert settlement.scores[0].source_excerpt == "agent-loop 的出处摘录"
    finally:
        store.close()


class MisconceptionScorer:
    """第一次把 session_misconception 写成字符串，第二次返回对象。"""

    def __init__(self) -> None:
        self.calls = 0

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        match = re.search(r"题目 id：(\d+)", user_prompt)
        question_id = match.group(1) if match else "0"
        base = {
            "questions": [
                {
                    "id": question_id,
                    "score": 70,
                    "why": "方向对",
                    "misconception_hit": False,
                    "certain": False,
                }
            ]
        }
        if self.calls == 1:
            base["session_misconception"] = "把 workflow 当成 agent"
        else:
            base["session_misconception"] = {
                "text": "把 workflow 当成 agent",
                "concept_key": "agent-loop",
            }
        return json.dumps(base, ensure_ascii=False)


def test_string_session_misconception_triggers_retry() -> None:
    scorer = MisconceptionScorer()
    store, coach, _ = make_coach(scorer=scorer)
    try:
        started = asyncio.run(coach.start())
        result = asyncio.run(
            coach.answer(started.session_id, started.questions[0].id, "我的回答")
        )

        assert result.score == 70
        assert scorer.calls == 2
    finally:
        store.close()


def test_generated_reference_answer_wins_over_scorer() -> None:
    scorer = ScriptedScorer(reference_answer="模型参考答案")
    store, coach, _ = make_coach(
        scorer=scorer, generator=FakeQuestionGenerator()
    )
    try:
        started = asyncio.run(coach.start())
        result = asyncio.run(
            coach.answer(started.session_id, started.questions[0].id, "我的回答")
        )

        assert "先做核心流程" in result.why
        assert "模型参考答案" not in result.why
    finally:
        store.close()


def test_clip_sentence_keeps_short_text() -> None:
    assert clip_sentence("短答案。") == "短答案。"


def test_clip_sentence_ends_on_sentence_mark() -> None:
    text = "第一句给结论。" + "第二句补依据，很长的依据。" * 10
    clipped = clip_sentence(text, limit=30)
    assert len(clipped) <= 30
    assert clipped.endswith("。")


def test_clip_sentence_falls_back_to_ellipsis() -> None:
    assert clip_sentence("没有标点的一段话" * 6, limit=12).endswith("…")
    assert clip_sentence("逗号分开的一段，后面还有内容", limit=10).endswith("…")


def test_clip_sentence_never_cuts_mid_character_without_ellipsis() -> None:
    clipped = clip_sentence("很长的一段没有句号的话" * 20, limit=40)
    assert clipped.endswith("…")
    assert len(clipped) <= 41
