"""单元结束后的异步记忆提炼：一次重试、短事务写入、审计表。"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from datetime import datetime

from core.memory import HALF_LIFE_DAYS, recall_update
from core.memory_extraction import (
    MemoryDraft,
    build_extraction_messages,
    initial_strength,
    normalize_text,
    parse_memories,
)
from core.ports import JsonScorer
from core.store import Store

logger = logging.getLogger(__name__)


class MemoryExtractor:
    def __init__(
        self,
        store: Store,
        scorer: JsonScorer,
        *,
        user_id: str = "owner",
        clock: Callable[[], datetime] = datetime.now,
        rng: Callable[[float, float], float] = random.uniform,
        max_attempts: int = 2,
    ) -> None:
        self._store = store
        self._scorer = scorer
        self._user_id = user_id
        self._clock = clock
        self._rng = rng
        self._max_attempts = max_attempts

    async def run(self, session_id: str) -> None:
        if self._store.memory_run_exists(self._user_id, session_id):
            return
        started_at = self._timestamp()
        run_id: int | None = None
        try:
            run_id = self._store.start_memory_run(
                user_id=self._user_id,
                session_id=session_id,
                started_at=started_at,
            )
            user_texts = self._store.user_texts_for_session(session_id)
            if not user_texts:
                self._finish(run_id, "empty", 0, None)
                return

            system_prompt, user_prompt = build_extraction_messages(user_texts)
            drafts: list[MemoryDraft] | None = None
            last_error = ""
            for _ in range(self._max_attempts):
                try:
                    raw = await self._scorer.grade(system_prompt, user_prompt)
                    drafts = parse_memories(raw, user_texts)
                    break
                except Exception as exc:
                    last_error = str(exc)
                    logger.warning("memory_extraction_retry: %s", exc)

            if drafts is None:
                self._finish(run_id, "failed", 0, last_error[:500])
                return

            count = self._persist(drafts, session_id)
            self._finish(
                run_id, "succeeded" if count else "empty", count, None
            )
        except Exception as exc:
            logger.exception("memory_extraction_failed")
            if run_id is not None:
                self._finish(run_id, "failed", 0, str(exc)[:500])

    def _persist(self, drafts: list[MemoryDraft], session_id: str) -> int:
        if not drafts:
            return 0
        now = self._clock()
        timestamp = now.isoformat(timespec="seconds")
        count = 0
        with self._store.transaction():
            existing = {
                (memory["kind"], normalize_text(memory["text"])): memory
                for memory in self._store.user_memories(self._user_id)
            }
            for draft in drafts:
                key = (draft.kind, normalize_text(draft.text))
                memory = existing.get(key)
                if memory is not None:
                    updates = recall_update(
                        memory, now, strong=True, rng=self._rng
                    )
                    self._store.update_memory_recall(memory["id"], **updates)
                    existing[key] = {**memory, **updates}
                else:
                    memory_id = self._store.add_user_memory(
                        user_id=self._user_id,
                        kind=draft.kind,
                        text=draft.text,
                        source_quote=draft.source_quote,
                        source_session_id=session_id,
                        source_question_id=draft.source_question_id,
                        strength=initial_strength(draft.kind),
                        half_life_days=HALF_LIFE_DAYS,
                        last_recalled_at=timestamp,
                        created_at=timestamp,
                    )
                    existing[key] = {
                        "id": memory_id,
                        "kind": draft.kind,
                        "text": draft.text,
                        "strength": initial_strength(draft.kind),
                        "half_life_days": HALF_LIFE_DAYS,
                        "last_recalled_at": timestamp,
                        "recall_count": 0,
                    }
                count += 1
        return count

    def _finish(
        self, run_id: int, status: str, count: int, error: str | None
    ) -> None:
        self._store.finish_memory_run(
            run_id,
            status=status,
            memory_count=count,
            error=error,
            finished_at=self._timestamp(),
        )

    def _timestamp(self) -> str:
        return self._clock().isoformat(timespec="seconds")
