from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import AsyncIterator, Sequence

from core.agent import Agent
from core.coach import Coach
from core.concepts import load_concepts
from core.db import connect, init_schema
from core.fixture import load_fixture
from core.ports import ChatMessage
from core.question_generation import (
    GeneratedQuestion,
    GeneratedSet,
    GenerationError,
    build_rubric,
)
from core.store import Store

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "seeds" / "fixture"
CONCEPTS_PATH = FIXTURE_DIR / "fixture-concepts.yaml"
BANK_PATH = FIXTURE_DIR / "fixture-question-bank.json"


class FakeQuestionGenerator:
    """按 plan 生成 5 道合法题；用于 Coach 测试，不依赖模型。"""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def generate(self, plan) -> GeneratedSet:
        self.calls += 1
        if self.error is not None:
            raise self.error
        concepts = {
            concept.id: concept
            for concept in (plan.main_concept, plan.review_concept)
            if concept is not None
        }
        questions = []
        for slot in plan.slots:
            concept = concepts[slot.concept_id]
            answer = "先做核心流程，再根据客户反馈决定是否扩展。"
            questions.append(
                GeneratedQuestion(
                    slot=slot.slot,
                    concept_id=slot.concept_id,
                    question_type=slot.question_type,
                    question_text=(
                        f"{concept.name} 第 {slot.slot} 题：客户预算有限时，"
                        "你会怎么选、放弃什么、怎么判断有效？"
                    ),
                    reference_answer=answer,
                    rubric=build_rubric(
                        question_type=slot.question_type,
                        must_have=("说清选择", "说清代价"),
                        red_flags=("只背定义",),
                        reference_answer=answer,
                    ),
                    source_chunk_id=f"fixture-{slot.concept_id}-{slot.slot}",
                    source_url=f"fixture://{slot.concept_id}",
                    source_excerpt=f"{slot.concept_id} 的出处摘录",
                )
            )
        return GeneratedSet(
            questions=tuple(questions),
            meta={
                "origin": "generated",
                "model": "fake-qgen",
                "prompt_version": "qgen-v1",
                "retrieved_chunk_ids": [],
                "repair_count": 0,
                "validation": "passed",
            },
        )


class FailingQuestionGenerator:
    def __init__(self, message: str = "生成失败") -> None:
        self.message = message
        self.calls = 0

    async def generate(self, plan) -> GeneratedSet:
        self.calls += 1
        raise GenerationError(self.message)


class FakeClock:
    def __init__(self, today: str = "2026-11-23", now: str = "2026-11-23T20:00:00") -> None:
        self._today = today
        self._now = now

    def today(self) -> str:
        return self._today

    def tomorrow(self) -> str:
        return (date.fromisoformat(self._today) + timedelta(days=1)).isoformat()

    def now(self) -> str:
        return self._now


class ScriptedScorer:
    """按脚本返回原始评分 JSON；脚本为空时按题目 id 返回固定分。"""

    def __init__(
        self,
        script: list[object] | None = None,
        *,
        score: int = 70,
        why: str = "方向对",
        reference_answer: str = "",
    ) -> None:
        self.script = list(script or [])
        self.score = score
        self.why = why
        self.reference_answer = reference_answer
        self.calls = 0

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return str(item)
        match = re.search(r"题目 id：(\d+)", user_prompt)
        question_id = match.group(1) if match else "0"
        return json.dumps(
            {
                "questions": [
                    {
                        "id": question_id,
                        "score": self.score,
                        "why": self.why,
                        "reference_answer": self.reference_answer,
                        "misconception_hit": False,
                        "certain": False,
                    }
                ],
                "session_misconception": None,
            },
            ensure_ascii=False,
        )


class ScriptedLLM:
    """按脚本返回追问文本；脚本为空时用模板。"""

    name = "scripted-llm"
    supports_streaming = False

    def __init__(
        self, answers: list[str] | None = None, *, error: Exception | None = None
    ) -> None:
        self.answers = list(answers or [])
        self.error = error
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.answers:
            return self.answers.pop(0)
        return "能举个例子吗？"

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        async def generate() -> AsyncIterator[str]:
            yield await self.complete(messages, temperature=temperature, max_tokens=max_tokens)

        return generate()


def make_store() -> Store:
    conn = connect(":memory:")
    init_schema(conn)
    return Store(conn)


def make_coach(
    *,
    today: str = "2026-11-23",
    scorer: object | None = None,
    clock: FakeClock | None = None,
    generator: object | None = None,
) -> tuple[Store, Coach, FakeClock]:
    store = make_store()
    load_fixture(store, CONCEPTS_PATH, BANK_PATH)
    concepts = load_concepts(CONCEPTS_PATH)
    clock = clock or FakeClock(today)
    coach = Coach(
        store,
        concepts,
        clock=clock,
        scorer=scorer or ScriptedScorer(),
        generator=generator,  # type: ignore[arg-type]
    )
    return store, coach, clock


def make_agent(
    store: Store,
    *,
    today: str = "2026-11-23",
    scorer: object | None = None,
    llm: object | None = None,
    generator: object | None = None,
) -> tuple[Agent, FakeClock]:
    concepts = load_concepts(CONCEPTS_PATH)
    clock = FakeClock(today)
    coach = Coach(
        store,
        concepts,
        clock=clock,
        scorer=scorer or ScriptedScorer(),
        generator=generator,  # type: ignore[arg-type]
    )
    agent = Agent(store, coach, clock=clock, llm=llm or ScriptedLLM())
    return agent, clock
