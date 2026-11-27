"""第一片 Agent：最小路由、会话生命周期与 probe。

Agent 不写业务规则：配比、评分、结算都交给 Coach；这里只决定
「这句话是作答 / 不知道 / 知道了」，并维护 agent_sessions 的活跃状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .clock import Clock
from .coach import Coach, ScoredAnswer, Settlement, StartedSession
from .ports import ChatMessage, LLMProvider
from .router import classify
from .store import SessionAlreadyFinalized, Store

PROBE_TEMPLATE = "能举个例子吗？"
PROBE_SKIP_TEXT = "已跳过"
PROBE_SYSTEM_PROMPT = (
    "你是中文学习伴侣的追问者。只输出一个简短的中文追问，"
    "针对用户回答里最薄弱的一点，不要评分、不要解释。"
)


@dataclass(frozen=True, slots=True)
class Turn:
    kind: str  # scored | probe | skipped | settled
    answer: ScoredAnswer | None = None
    probe: str | None = None
    settlement: Settlement | None = None
    next_question: dict[str, Any] | None = None
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class Resume:
    expired: bool
    session_id: str | None = None
    question: dict[str, Any] | None = None
    settlement: Settlement | None = None


class Agent:
    def __init__(
        self,
        store: Store,
        coach: Coach,
        *,
        clock: Clock,
        llm: LLMProvider,
    ) -> None:
        self._store = store
        self._coach = coach
        self._clock = clock
        self._llm = llm

    async def start(self) -> StartedSession:
        self._store.abandon_stale_agent_sessions(
            today=self._clock.today(), updated_at=self._clock.now()
        )
        return await self._coach.start()

    def resume(self, session_id: str) -> Resume:
        today = self._clock.today()
        agent = self._store.agent_session(session_id)
        if agent is None or agent["status"] != "active" or agent["date"] != today:
            if agent is not None and agent["status"] == "active":
                self._store.abandon_stale_agent_sessions(
                    today=today, updated_at=self._clock.now()
                )
            return Resume(expired=True)

        question = self._next_pending(session_id)
        if question is not None:
            return Resume(expired=False, session_id=session_id, question=question)

        settlement = self._coach.finish(session_id)
        return Resume(expired=False, session_id=session_id, settlement=settlement)

    async def submit(
        self,
        session_id: str,
        question_id: int,
        text: str,
        *,
        input_mode: str = "text",
        retry: bool = False,
    ) -> Turn:
        question = self._store.question(question_id)
        if question is None or question["session_id"] != session_id:
            raise KeyError(f"题目不存在或不属于该会话：{question_id}")
        agent_session = self._store.agent_session(session_id)
        answered = question["score"] is not None or bool(
            (question.get("answer_text") or "").strip()
        )
        if answered and not retry:
            return self._duplicate_turn(session_id, question, agent_session)
        if agent_session is None or agent_session["status"] != "active":
            raise SessionAlreadyFinalized(f"会话已结束：{session_id}")

        if retry:
            # 重答：跳过复述/追问等分流，直接重新打分并覆盖同一行。
            answer = await self._coach.answer(
                session_id, question_id, text, input_mode=input_mode, retry=True
            )
            return self._after_scored(session_id, answer)

        intent = classify(text)

        if intent == "dont_know":
            answer = self._coach.mark_unknown(
                session_id, question_id, input_mode=input_mode
            )
            return self._after_scored(session_id, answer)

        if intent == "knows":
            self._require_open_question(session_id, question_id)
            if self._probe_count(session_id, question_id) == 0:
                probe = await self._probe(question_id, text)
                self._store.add_session_note(
                    session_id=session_id,
                    question_id=question_id,
                    mode="probe",
                    input_text=text,
                    output_text=probe,
                    created_at=self._clock.now(),
                )
                return Turn(
                    kind="probe",
                    probe=probe,
                    next_question=self._store.question(question_id),
                )

            self._store.add_session_note(
                session_id=session_id,
                question_id=question_id,
                mode="probe",
                input_text=text,
                output_text=PROBE_SKIP_TEXT,
                created_at=self._clock.now(),
            )
            return self._advance(session_id, kind="skipped")

        answer = await self._coach.answer(
            session_id, question_id, text, input_mode=input_mode
        )
        return self._after_scored(session_id, answer)

    def finish(self, session_id: str) -> Settlement:
        return self._coach.finish(session_id)

    def fallback_to_text(self, session_id: str, question_id: int) -> None:
        """ASR 失败：把该题切到文字输入，不阻塞会话。"""
        self._store.touch_agent_session(
            session_id,
            last_question_id=question_id,
            input_mode="text",
            updated_at=self._clock.now(),
        )

    def skip(self, session_id: str, question_id: int) -> Turn:
        """手动切下一题：该题记未作答，不写分数；重复跳过不重复记。"""
        self._require_open_question(session_id, question_id)
        notes = self._store.session_notes(session_id)
        if any(
            note["mode"] == "probe"
            and note["question_id"] == question_id
            and note["output_text"] == PROBE_SKIP_TEXT
            for note in notes
        ):
            return self._advance(session_id, kind="skipped")
        self._store.add_session_note(
            session_id=session_id,
            question_id=question_id,
            mode="probe",
            input_text="跳过",
            output_text=PROBE_SKIP_TEXT,
            created_at=self._clock.now(),
        )
        return self._advance(session_id, kind="skipped")

    # ---- 内部 ----

    def _after_scored(self, session_id: str, answer: ScoredAnswer) -> Turn:
        question = self._next_pending(session_id)
        if question is not None:
            return Turn(kind="scored", answer=answer, next_question=question)

        settlement = self._coach.finish(session_id)
        return Turn(kind="settled", answer=answer, settlement=settlement)

    def _duplicate_turn(
        self,
        session_id: str,
        question: dict[str, Any],
        agent_session: dict[str, Any] | None,
    ) -> Turn:
        score = question["score"]
        answer = ScoredAnswer(
            question_id=int(question["id"]),
            score=int(score) if score is not None else None,
            why=str(question.get("feedback") or ""),
            speak=False,
            question_type=question.get("question_type"),
            source_url=question.get("source_url"),
            source_excerpt=question.get("source_excerpt"),
        )
        if agent_session is None or agent_session["status"] != "active":
            # 已结束场的重复提交：返回已有分数即可；结果卡已经在第一次结算时发过。
            return Turn(kind="scored", answer=answer, duplicate=True)
        next_question = self._next_pending(session_id)
        if next_question is not None:
            return Turn(
                kind="scored",
                answer=answer,
                next_question=next_question,
                duplicate=True,
            )
        settlement = self._coach.finish(session_id)
        return Turn(
            kind="settled",
            answer=answer,
            settlement=settlement,
            duplicate=True,
        )

    def current_question(self, session_id: str) -> dict[str, Any] | None:
        """当前应当展示的未作答题；供会话内教学/澄清校验。"""
        return self._next_pending(session_id)

    def _advance(self, session_id: str, *, kind: str) -> Turn:
        question = self._next_pending(session_id)
        if question is not None:
            return Turn(kind=kind, next_question=question)

        settlement = self._coach.finish(session_id)
        return Turn(kind="settled", settlement=settlement)

    def _next_pending(self, session_id: str) -> dict[str, Any] | None:
        skipped = {
            note["question_id"]
            for note in self._store.session_notes(session_id)
            if note["mode"] == "probe" and note["output_text"] == PROBE_SKIP_TEXT
        }
        for question in self._store.session_questions(session_id):
            if question["answer_text"] is not None or question["score"] is not None:
                continue
            if question["id"] in skipped:
                continue
            return question
        return None

    def _require_open_question(self, session_id: str, question_id: int) -> dict[str, Any]:
        question = self._store.question(question_id)
        if question is None or question["session_id"] != session_id:
            raise KeyError(f"题目不存在或不属于该会话：{question_id}")
        if question["answer_text"] is not None or question["score"] is not None:
            raise ValueError(f"题目已作答：{question_id}")
        return question

    def _probe_count(self, session_id: str, question_id: int) -> int:
        return sum(
            1
            for note in self._store.session_notes(session_id)
            if note["mode"] == "probe"
            and note["question_id"] == question_id
            and note["output_text"] != PROBE_SKIP_TEXT
        )

    async def _probe(self, question_id: int, answer_text: str) -> str:
        question = self._store.question(question_id)
        if question is None:
            return PROBE_TEMPLATE
        messages = [
            ChatMessage(role="system", content=PROBE_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=(
                    f"题目：{question['question_text']}\n"
                    f"评分标准：{question.get('rubric_json') or '{}'}\n"
                    f"用户回答：{answer_text}\n"
                    "请针对回答薄弱处追问一个具体问题。"
                ),
            ),
        ]
        try:
            probe = (await self._llm.complete(messages, temperature=0.3, max_tokens=120)).strip()
        except Exception:
            return PROBE_TEMPLATE
        return probe or PROBE_TEMPLATE
