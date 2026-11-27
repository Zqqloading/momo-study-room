"""第一片 Coach：选题、逐题评分、结算、mastery 与次日复习。

业务规则只在这里；BFF 不写 SQL，Agent 不做配比与结算。
"""

from __future__ import annotations

import json
import math
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

from .clock import Clock
from .concepts import Concept
from .models import (
    ConceptAssessment,
    ConceptState,
    ConceptUnitResult,
    Focus,
    ProposalConcept,
    ProposalPrerequisite,
    ProposalSlot,
    SessionRecord,
    SessionResult,
    UnitProposal,
    mastery_label,
)
from .planner import UNLOCK_MASTERY
from .ports import JsonScorer, QuestionScore
from .question_generation import (
    QUESTION_TYPE_LABELS,
    GeneratedSet,
    GenerationError,
    QuestionGenerator,
    SessionPlan,
    Slot,
    build_session_plan,
)
from .scoring import build_score_messages, parse_score_result
from .selection import TopicSelection, select_topic
from .store import SessionAlreadyFinalized, Store

CHOICE_SCORE_CORRECT = 100
CHOICE_SCORE_WRONG = 40
REVIEW_THRESHOLD = 80
SHORT_DEFINITION_CHARS = 60
REFERENCE_MAX_CHARS = 120


def clip_sentence(text: str, limit: int = REFERENCE_MAX_CHARS) -> str:
    """超长时在句子边界收住；实在没有标点才硬切补省略号。"""
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    window = cleaned[:limit]
    for mark in ("。", "！", "？", "；"):
        index = window.rfind(mark)
        if index > 0:
            return window[: index + 1]
    for mark in ("，", "、"):
        index = window.rfind(mark)
        if index > 0:
            return f"{window[:index]}…"
    return f"{window.rstrip()}…"


class NoSessionAvailable(RuntimeError):
    """没有可出的新题，也没有到期复习题。"""


@dataclass(frozen=True, slots=True)
class SessionQuestion:
    id: int
    role: str
    kind: str
    text: str
    options: dict[str, str] | None
    index: int
    total: int
    question_type: str | None = None
    origin: str | None = None


@dataclass(frozen=True, slots=True)
class StartedSession:
    session_id: str
    kind: str
    questions: tuple[SessionQuestion, ...]
    intro: str = ""
    focus: Focus | None = None


@dataclass(frozen=True, slots=True)
class ScoredAnswer:
    question_id: int
    score: int | None
    why: str
    speak: bool = True  # 是否朗读反馈（辨析题答对不朗读）
    question_type: str | None = None
    source_url: str | None = None
    source_excerpt: str | None = None


@dataclass(frozen=True, slots=True)
class Settlement:
    session_id: str
    status: str
    session_score: float | None
    mastery: dict[str, int]
    review_due_at: str | None
    scores: tuple[ScoredAnswer, ...]
    concepts: tuple[ConceptUnitResult, ...] = ()


def _normalize_choice(text: str) -> str:
    cleaned = text.strip().upper()
    for char in cleaned:
        if char in "ABCD":
            return char
    return cleaned


def _date_diff(later: str, earlier: str) -> int | None:
    try:
        return (date.fromisoformat(later) - date.fromisoformat(earlier)).days
    except ValueError:
        return None


def _overdue_days(due_at: str | None, today: str) -> int:
    if not due_at:
        return 0
    days = _date_diff(today, due_at)
    return max(0, days) if days is not None else 0


def _options(raw: Any) -> dict[str, str] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return {str(key): str(value) for key, value in parsed.items()} if isinstance(parsed, dict) else None
    return None


class Coach:
    def __init__(
        self,
        store: Store,
        concepts: list[Concept],
        *,
        clock: Clock,
        scorer: JsonScorer,
        generator: QuestionGenerator | None = None,
    ) -> None:
        self._store = store
        self._concepts = {concept.id: concept for concept in concepts}
        self._clock = clock
        self._scorer = scorer
        self._generator = generator

    # ---- 会话启动与提议 ----

    def _select_plan(
        self,
        states: list[ConceptState],
        due: list[ConceptState],
        today: str,
    ) -> (
        tuple[Concept | None, Concept | None, SessionPlan, TopicSelection | None]
        | None
    ):
        active_ids = [state.id for state in states if state.status == "active"]
        assessments = self._store.latest_concept_assessments(active_ids)
        selection = select_topic(
            states, assessments, list(self._concepts.values()), today
        )
        main_concept = (
            self._concepts.get(selection.state.id) if selection is not None else None
        )
        review_state = next(
            (state for state in due if state.id in self._concepts), None
        )
        review_concept = (
            self._concepts[review_state.id] if review_state is not None else None
        )
        if main_concept is None and review_concept is None:
            return None
        return (
            main_concept,
            review_concept,
            build_session_plan(
                main_concept=main_concept, review_concept=review_concept
            ),
            selection,
        )

    def propose(self) -> UnitProposal:
        """只读预览今天学什么；不写库、不生成题目、不调模型。"""
        today = self._clock.today()
        states = self._store.concept_states()
        due = [
            state
            for state in self._store.due_reviews(today)
            if state.id in self._concepts
        ]
        selected = self._select_plan(states, due, today)
        if selected is None:
            active = [
                state
                for state in states
                if state.status == "active" and state.id in self._concepts
            ]
            reason = (
                "没有在学概念，也没有到期复习"
                if not active
                else "没有可解锁的新概念，也没有到期复习"
            )
            return UnitProposal(available=False, date=today, reason=reason)

        main_concept, review_concept, plan, selection = selected
        states_by_id = {state.id: state for state in states}
        main_card = None
        review_card = None
        if main_concept is not None:
            main_state = states_by_id.get(
                main_concept.id, ConceptState(id=main_concept.id)
            )
            main_card = self._proposal_concept(
                main_concept,
                main_state,
                states_by_id,
                today,
                role="main",
                reason_kind=(
                    selection.reason_kind if selection is not None else "lowest_mastery"
                ),
                assessment=selection.assessment if selection is not None else None,
            )
        if review_concept is not None:
            review_state = states_by_id.get(
                review_concept.id, ConceptState(id=review_concept.id)
            )
            review_card = self._proposal_concept(
                review_concept,
                review_state,
                states_by_id,
                today,
                role="review",
                reason_kind="review",
            )

        slots = tuple(
            ProposalSlot(
                slot=slot.slot,
                question_type=slot.question_type,
                label=QUESTION_TYPE_LABELS.get(slot.question_type, slot.question_type),
                role=slot.role,
                concept_id=slot.concept_id,
            )
            for slot in plan.slots
        )
        return UnitProposal(
            available=True,
            date=today,
            kind=plan.kind,
            question_count=len(slots),
            deferred_reviews=max(0, len(due) - (1 if review_concept else 0)),
            main=main_card,
            review=review_card,
            same_concept=(
                main_concept is not None
                and review_concept is not None
                and main_concept.id == review_concept.id
            ),
            slots=slots,
        )

    def _proposal_concept(
        self,
        concept: Concept,
        state: ConceptState,
        states_by_id: dict[str, ConceptState],
        today: str,
        *,
        role: str,
        reason_kind: str = "",
        assessment: ConceptAssessment | None = None,
    ) -> ProposalConcept:
        scores = self._store.recent_concept_scores(concept.id, limit=1)
        last_score = scores[0] if scores else None
        prerequisites = (
            tuple(
                self._proposal_prerequisite(concept_id, states_by_id)
                for concept_id in concept.prerequisites
            )
            if role == "main"
            else ()
        )
        reason = (
            self._main_reason(
                concept, state, states_by_id, today, reason_kind, assessment
            )
            if role == "main"
            else self._review_reason(state, last_score, today)
        )
        return ProposalConcept(
            id=concept.id,
            name=concept.name,
            plain_def=concept.plain_def,
            difficulty=concept.difficulty,
            mastery=state.mastery,
            mastery_label=mastery_label(state.mastery),
            last_seen=state.last_seen,
            review_due_at=state.review_due_at,
            overdue_days=_overdue_days(state.review_due_at, today),
            last_score=last_score,
            prerequisites=prerequisites,
            reason=reason,
            reason_kind=reason_kind,
        )

    def _proposal_prerequisite(
        self, concept_id: str, states_by_id: dict[str, ConceptState]
    ) -> ProposalPrerequisite:
        concept = self._concepts.get(concept_id)
        state = states_by_id.get(concept_id)
        mastery = state.mastery if state is not None else 0
        satisfied = state is not None and (
            mastery >= UNLOCK_MASTERY or state.status == "skipped"
        )
        return ProposalPrerequisite(
            id=concept_id,
            name=concept.name if concept is not None else concept_id,
            mastery=mastery,
            satisfied=satisfied,
        )

    def _main_reason(
        self,
        concept: Concept,
        state: ConceptState,
        states_by_id: dict[str, ConceptState],
        today: str,
        reason_kind: str,
        assessment: ConceptAssessment | None,
    ) -> str:
        parts: list[str] = []
        if reason_kind == "recent_miss" and assessment is not None:
            if assessment.min_score < 60:
                parts.append(f"上次得分 {assessment.min_score:g}，低于 60")
            else:
                parts.append(f"上次均分 {assessment.avg_score:g}，低于 80")
            parts.append(f"最近一次作答 {assessment.date}")
        elif reason_kind == "lowest_mastery":
            if state.last_seen:
                days = _date_diff(today, state.last_seen)
                if days is not None and days > 0:
                    parts.append(f"上次学过 {state.last_seen}，已 {days} 天没学")
                else:
                    parts.append(f"上次学过 {state.last_seen}")
            parts.append(f"掌握度最低（mastery {state.mastery}）")
        else:
            parts.append("从未学过")
            parts.append("没有失手，也没有掌握度差异，按天随机选一个")
        if concept.prerequisites:
            items = []
            for concept_id in concept.prerequisites:
                prerequisite = self._concepts.get(concept_id)
                name = prerequisite.name if prerequisite is not None else concept_id
                prerequisite_state = states_by_id.get(concept_id)
                if prerequisite_state is not None and prerequisite_state.status == "skipped":
                    items.append(f"{name} 已跳过")
                elif prerequisite_state is not None:
                    items.append(f"{name}（mastery {prerequisite_state.mastery}）")
                else:
                    items.append(f"{name} 未满足")
            parts.append("前置已满足：" + "、".join(items))
        return "；".join(parts)

    def _review_reason(
        self,
        state: ConceptState,
        last_score: float | None,
        today: str,
    ) -> str:
        days = _overdue_days(state.review_due_at, today)
        parts = [f"复习已到期 {days} 天" if days > 0 else "今天到期"]
        if last_score is not None:
            text = f"上次得分 {last_score:g}"
            if last_score < REVIEW_THRESHOLD:
                text += f"，低于 {REVIEW_THRESHOLD}"
            parts.append(text)
        return "；".join(parts)

    async def start(self) -> StartedSession:
        today = self._clock.today()
        now = self._clock.now()

        states = self._store.concept_states()
        due = self._store.due_reviews(today)
        selected = self._select_plan(states, due, today)
        if selected is None:
            raise NoSessionAvailable("没有可出的新题，也没有到期复习题")
        main_concept, review_concept, plan, selection = selected
        generated, fallback_reason = await self._generate(plan)

        session_id = uuid.uuid4().hex
        concept_id = plan.main_concept.id if plan.main_concept is not None else None
        self._store.start_agent_session(
            session_id=session_id,
            kind=plan.kind,
            date=today,
            started_at=now,
            concept_id=concept_id,
            input_mode="text",
        )

        if generated is not None:
            questions = self._insert_generated(session_id, plan, generated, now)
        else:
            questions = self._insert_fallback(
                session_id, plan, now, fallback_reason or "生成失败"
            )

        intro, focus = self._intro_for(
            selection, main_concept, review_concept
        )
        return StartedSession(
            session_id=session_id,
            kind=plan.kind,
            questions=tuple(questions),
            intro=intro,
            focus=focus,
        )

    def _intro_for(
        self,
        selection: TopicSelection | None,
        main_concept: Concept | None,
        review_concept: Concept | None,
    ) -> tuple[str, Focus | None]:
        if selection is not None and main_concept is not None:
            text = self._intro_text(
                main_concept,
                selection.state,
                selection.reason_kind,
                selection.assessment,
            )
            return text, Focus(
                concept_id=main_concept.id,
                name=main_concept.name,
                reason_kind=selection.reason_kind,
            )
        if review_concept is not None:
            return (
                f"今天先复习「{review_concept.name}」。",
                Focus(
                    concept_id=review_concept.id,
                    name=review_concept.name,
                    reason_kind="review",
                ),
            )
        return "", None

    @staticmethod
    def _intro_text(
        concept: Concept,
        state: ConceptState,
        reason_kind: str,
        assessment: ConceptAssessment | None,
    ) -> str:
        name = concept.name
        if reason_kind == "recent_miss" and assessment is not None:
            if assessment.min_score < 60:
                return (
                    f"上次「{name}」这道题你没答好（最低 {assessment.min_score:g} 分），"
                    "今天先把它补上。"
                )
            return (
                f"上次「{name}」平均 {assessment.avg_score:g} 分，没到 80，"
                "今天先巩固一下。"
            )
        if reason_kind == "lowest_mastery" and state.last_seen is not None:
            return (
                f"现在掌握度最低的是「{name}」（{mastery_label(state.mastery)}），"
                "今天先学它。"
            )
        return f"今天从「{name}」开始。"

    async def _generate(
        self, plan: SessionPlan
    ) -> tuple[GeneratedSet | None, str | None]:
        if self._generator is None:
            return None, "未配置出题生成器"
        try:
            return await self._generator.generate(plan), None
        except GenerationError as exc:
            return None, str(exc)

    def _insert_generated(
        self, session_id: str, plan: SessionPlan, generated: GeneratedSet, now: str
    ) -> list[SessionQuestion]:
        slots = {slot.slot: slot for slot in plan.slots}
        total = len(generated.questions)
        questions: list[SessionQuestion] = []
        for index, item in enumerate(generated.questions, start=1):
            slot = slots[item.slot]
            kind = "recall" if item.question_type == "concept" else "apply"
            question_id = self._store.add_question(
                session_id=session_id,
                question_bank_id=None,
                concept_id=item.concept_id,
                role=slot.role,
                kind=kind,
                question_type=item.question_type,
                text=item.question_text,
                rubric_json=item.rubric,
                source_url=item.source_url,
                source_excerpt=item.source_excerpt,
                source_chunk_id=item.source_chunk_id,
                generation_meta_json=generated.meta,
                created_at=now,
            )
            questions.append(
                SessionQuestion(
                    id=question_id,
                    role=slot.role,
                    kind=kind,
                    text=item.question_text,
                    options=None,
                    index=index,
                    total=total,
                    question_type=item.question_type,
                    origin=str(generated.meta.get("origin") or "generated"),
                )
            )
        return questions

    def _insert_fallback(
        self, session_id: str, plan: SessionPlan, now: str, reason: str
    ) -> list[SessionQuestion]:
        rows = self._fallback_rows(plan)
        total = len(rows)
        meta = {"origin": "fallback", "reason": reason}
        questions: list[SessionQuestion] = []
        for index, (row, slot) in enumerate(rows, start=1):
            question_id = self._store.add_question(
                session_id=session_id,
                question_bank_id=str(row["id"]),
                concept_id=row.get("concept_id"),
                role=slot.role,
                kind=str(row["kind"]),
                text=str(row["question_text"]),
                rubric_json=row["rubric_json"],
                options_json=row.get("options_json"),
                answer_key=row.get("answer_key"),
                source_url=str(row["source_url"]),
                source_excerpt=str(row["source_excerpt"]),
                generation_meta_json=meta,
                created_at=now,
            )
            questions.append(
                SessionQuestion(
                    id=question_id,
                    role=slot.role,
                    kind=str(row["kind"]),
                    text=str(row["question_text"]),
                    options=_options(row.get("options_json")),
                    index=index,
                    total=total,
                    origin="fallback",
                )
            )
        return questions

    def _fallback_rows(
        self, plan: SessionPlan
    ) -> list[tuple[dict[str, Any], Slot]]:
        counts = Counter(slot.concept_id for slot in plan.slots)
        picked: dict[str, list[dict[str, Any]]] = {}
        for concept_id, wanted in counts.items():
            bank = self._store.bank_questions(concept_id)
            if len(bank) < wanted:
                raise NoSessionAvailable(
                    f"生成失败且旧题库不足：{concept_id} 需要 {wanted} 题，"
                    f"只有 {len(bank)} 题"
                )
            usage = self._store.question_usage(concept_id)
            bank.sort(key=lambda row: (usage.get(str(row["id"]), 0), str(row["id"])))
            picked[concept_id] = bank[:wanted]

        positions: Counter[str] = Counter()
        rows: list[tuple[dict[str, Any], Slot]] = []
        for slot in plan.slots:
            row = picked[slot.concept_id][positions[slot.concept_id]]
            positions[slot.concept_id] += 1
            rows.append((row, slot))
        return rows

    # ---- 逐题作答 ----

    async def answer(
        self,
        session_id: str,
        question_id: int,
        text: str,
        *,
        input_mode: str = "text",
        retry: bool = False,
    ) -> ScoredAnswer:
        question = self._open_question(session_id, question_id, retry=retry)

        if question["kind"] == "discriminate":
            score, why, speak = self._score_choice(question, text)
        else:
            score, why = await self._score_open(question, text)
            speak = True

        self._store.save_answer(question_id, text=text, score=score, feedback=why)
        self._store.touch_agent_session(
            session_id,
            last_question_id=question_id,
            input_mode=input_mode,
            updated_at=self._clock.now(),
        )
        return ScoredAnswer(
            question_id=question_id,
            score=score,
            why=why,
            speak=speak,
            question_type=question.get("question_type"),
            source_url=question.get("source_url"),
            source_excerpt=question.get("source_excerpt"),
        )

    def mark_unknown(
        self, session_id: str, question_id: int, *, input_mode: str = "text"
    ) -> ScoredAnswer:
        question = self._open_question(session_id, question_id)
        concept = self._concepts.get(str(question.get("concept_id") or ""))
        why = self._short_definition(concept)
        self._store.save_answer(question_id, text="不知道", score=0, feedback=why)
        self._store.touch_agent_session(
            session_id,
            last_question_id=question_id,
            input_mode=input_mode,
            updated_at=self._clock.now(),
        )
        return ScoredAnswer(
            question_id=question_id,
            score=0,
            why=why,
            question_type=question.get("question_type"),
            source_url=question.get("source_url"),
            source_excerpt=question.get("source_excerpt"),
        )

    def _open_question(
        self, session_id: str, question_id: int, *, retry: bool = False
    ) -> dict[str, Any]:
        question = self._store.question(question_id)
        if question is None or question["session_id"] != session_id:
            raise KeyError(f"题目不存在或不属于该会话：{question_id}")
        if not retry and (
            question["score"] is not None or question["answer_text"] is not None
        ):
            raise ValueError(f"题目已作答：{question_id}")
        return question

    @staticmethod
    def _rubric_object(question: dict[str, Any]) -> dict[str, Any]:
        rubric = question.get("rubric_json")
        if isinstance(rubric, str):
            try:
                parsed = json.loads(rubric)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return rubric if isinstance(rubric, dict) else {}

    @staticmethod
    def _score_choice(question: dict[str, Any], text: str) -> tuple[int, str, bool]:
        key = str(question.get("answer_key") or "").strip().upper()
        if key and _normalize_choice(text) == key:
            return CHOICE_SCORE_CORRECT, "答对了", False

        options = _options(question.get("options_json")) or {}
        option_text = options.get(key, "")
        why = f"正确答案是 {key or '未知'}"
        if option_text:
            why += f"：{option_text}"

        rubric_obj = Coach._rubric_object(question)
        explanation = str(rubric_obj.get("explanation") or "").strip()
        criteria = str(rubric_obj.get("criteria") or "").strip()
        prefix = f"选 {key}："
        if criteria.startswith(prefix):
            criteria = criteria[len(prefix):].strip()

        # 解析不能只是复述选项文本；explanation 不合格时再用 criteria。
        candidate = ""
        for value in (explanation, criteria):
            if value and value.strip("。 ") != option_text.strip("。 "):
                candidate = value
                break
        if not candidate:
            candidate = "其余选项与题干条件或概念定义不符"
        why += f"。解析：{candidate}"
        return CHOICE_SCORE_WRONG, why, True

    async def _score_open(
        self, question: dict[str, Any], text: str
    ) -> tuple[int | None, str]:
        system_prompt, user_prompt = build_score_messages(question, text)
        # 适配器错误类型由各 provider 定义，core 只认端口；失败就重试一次。
        for _ in range(2):
            try:
                raw = await self._scorer.grade(system_prompt, user_prompt)
                result = parse_score_result(raw, expected_ids=[str(question["id"])])
                item = result.questions[0]
                rubric = self._rubric_object(question)
                reference = str(rubric.get("reference_answer") or "").strip()
                if not reference:
                    reference = item.reference_answer
                if not reference:
                    reference = str(rubric.get("criteria") or "").strip() or str(
                        rubric.get("explanation") or ""
                    ).strip()
                why = item.why
                if reference:
                    why = f"{why} 参考答案：{clip_sentence(reference)}"
                return item.score, why
            except Exception:
                continue
        return None, "本题未评分"

    @staticmethod
    def _short_definition(concept: Concept | None) -> str:
        if concept is None:
            return "记下这道题，之后再看。"
        text = f"{concept.plain_def} 例：{concept.source.excerpt}"
        if len(text) > SHORT_DEFINITION_CHARS:
            text = text[: SHORT_DEFINITION_CHARS - 1] + "…"
        return text

    # ---- 结算 ----

    def finish(self, session_id: str) -> Settlement:
        agent = self._store.agent_session(session_id)
        if agent is None:
            raise KeyError(f"agent_sessions 不存在：{session_id}")
        if agent["status"] != "active":
            raise SessionAlreadyFinalized(f"会话已结束：{session_id}")

        questions = self._store.session_questions(session_id)
        if not questions:
            raise ValueError(f"会话没有题目：{session_id}")

        scored = [question for question in questions if question["score"] is not None]
        answered = [
            question
            for question in questions
            if question["score"] is not None or (question.get("answer_text") or "").strip()
        ]

        if not scored:
            status = "unscored"
        elif len(answered) == len(questions) and len(scored) == len(questions):
            status = "completed"
        else:
            status = "partial"

        session_score = (
            round(sum(float(question["score"]) for question in scored) / len(scored), 1)
            if scored
            else None
        )

        mastery_updates: dict[str, int] = {}
        if status == "completed" and agent["kind"] == "daily":
            mastery_updates = self._mastery_updates(session_id, scored)

        due_updates = self._due_updates(agent, scored)
        mastery_before: dict[str, int] = {}
        for question in questions:
            concept_id = question.get("concept_id")
            if not concept_id:
                continue
            key = str(concept_id)
            if key in mastery_before:
                continue
            state = self._store.concept_state(key)
            mastery_before[key] = state.mastery if state is not None else 0
        now = self._clock.now()
        record = SessionRecord(
            session_id=session_id,
            date=str(agent["date"]),
            kind=str(agent["kind"]),
            status=status,
            started_at=str(agent["started_at"]),
            created_at=now,
            concept_id=agent.get("concept_id"),
            input_mode=str(agent["input_mode"]),
            session_score=session_score,
        )
        result = SessionResult(
            session_id=session_id,
            status=status,
            session_score=session_score,
            scores=tuple(
                QuestionScore(
                    question_id=str(question["id"]),
                    score=int(question["score"]),
                    why=str(question.get("feedback") or ""),
                )
                for question in scored
            ),
            mastery_updates=mastery_updates,
            due_updates=due_updates,
        )
        self._store.finalize(
            record,
            result,
            agent_session_id=session_id,
            finished_at=now,
        )

        concepts = self._concept_unit_results(
            questions, scored, mastery_updates, mastery_before
        )
        concept_id = agent.get("concept_id")
        review_due = (
            due_updates.get(str(concept_id), (None, None))[0] if concept_id else None
        )
        return Settlement(
            session_id=session_id,
            status=status,
            session_score=session_score,
            mastery=mastery_updates,
            review_due_at=review_due,
            concepts=concepts,
            scores=tuple(
                ScoredAnswer(
                    question_id=int(question["id"]),
                    score=int(question["score"]),
                    why=str(question.get("feedback") or ""),
                    question_type=question.get("question_type"),
                    source_url=question.get("source_url"),
                    source_excerpt=question.get("source_excerpt"),
                )
                for question in scored
            ),
        )

    def _concept_unit_results(
        self,
        questions: list[dict[str, Any]],
        scored: list[dict[str, Any]],
        mastery_updates: dict[str, int],
        mastery_before: dict[str, int],
    ) -> tuple[ConceptUnitResult, ...]:
        roles: dict[str, list[str]] = {}
        for question in questions:
            concept_id = question.get("concept_id")
            if not concept_id:
                continue
            key = str(concept_id)
            roles.setdefault(key, [])
            role = str(question["question_role"])
            if role not in roles[key]:
                roles[key].append(role)

        results: list[ConceptUnitResult] = []
        for concept_id, role_list in roles.items():
            new_values = [
                float(question["score"])
                for question in scored
                if str(question.get("concept_id")) == concept_id
                and question["question_role"] == "new"
                and question["score"] is not None
            ]
            review_values = [
                float(question["score"])
                for question in scored
                if str(question.get("concept_id")) == concept_id
                and question["question_role"] == "review"
                and question["score"] is not None
            ]
            state = self._store.concept_state(concept_id)
            before = mastery_before.get(concept_id, 0)
            after = state.mastery if state is not None else mastery_updates.get(
                concept_id, before
            )
            concept = self._concepts.get(concept_id)
            results.append(
                ConceptUnitResult(
                    concept_id=concept_id,
                    name=concept.name if concept is not None else concept_id,
                    roles=tuple(role_list),
                    new_score=(
                        round(sum(new_values) / len(new_values), 1)
                        if new_values
                        else None
                    ),
                    review_score=(
                        round(sum(review_values) / len(review_values), 1)
                        if review_values
                        else None
                    ),
                    mastery_before=before,
                    mastery_before_label=mastery_label(before),
                    mastery_after=after,
                    mastery_after_label=mastery_label(after),
                    mastery_updated=concept_id in mastery_updates,
                    review_due_at=state.review_due_at if state is not None else None,
                )
            )
        return tuple(results)

    def _mastery_updates(
        self, session_id: str, scored: list[dict[str, Any]]
    ) -> dict[str, int]:
        updates: dict[str, int] = {}
        concept_ids = {
            str(question["concept_id"])
            for question in scored
            if question["question_role"] == "new" and question["concept_id"]
        }
        for concept_id in concept_ids:
            values = [
                float(question["score"])
                for question in scored
                if question["question_role"] == "new"
                and question["concept_id"] == concept_id
            ]
            current = sum(values) / len(values)
            previous = self._store.recent_concept_scores(
                concept_id, limit=2, exclude_session=session_id
            )
            mean = (current + sum(previous)) / (1 + len(previous))
            updates[concept_id] = int(math.floor(mean / 20 + 0.5))
        return updates

    def _due_updates(
        self, agent: dict[str, Any], scored: list[dict[str, Any]]
    ) -> dict[str, tuple[str | None, str | None]]:
        today = str(agent["date"])
        tomorrow = self._clock.tomorrow()
        updates: dict[str, tuple[str | None, str | None]] = {}

        review_ids = {
            str(question["concept_id"])
            for question in scored
            if question["question_role"] == "review" and question["concept_id"]
        }
        for concept_id in review_ids:
            values = [
                float(question["score"])
                for question in scored
                if question["question_role"] == "review"
                and question["concept_id"] == concept_id
            ]
            average = sum(values) / len(values)
            state = self._store.concept_state(concept_id)
            if average < REVIEW_THRESHOLD:
                started = state.review_started_at if state and state.review_started_at else today
                updates[concept_id] = (tomorrow, started)
            else:
                updates[concept_id] = (None, None)

        if agent["kind"] == "daily" and agent.get("concept_id"):
            concept_id = str(agent["concept_id"])
            values = [
                float(question["score"])
                for question in scored
                if question["question_role"] == "new"
                and question["concept_id"] == concept_id
            ]
            if values:
                average = sum(values) / len(values)
                state = self._store.concept_state(concept_id)
                if average < REVIEW_THRESHOLD and state is not None and state.review_due_at is None:
                    # 第一片只排次日；不写 review_started_at（那是后续间隔复习的字段）。
                    updates[concept_id] = (tomorrow, state.review_started_at)

        return updates
