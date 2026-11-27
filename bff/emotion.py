"""情绪更新器：读衰减后的状态、调 scorer、夹取写回。

情绪层永远不能导致回复失败：超时、异常、非法 JSON 都退回
衰减后的旧状态。锁只包状态读写，模型调用在锁外。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import datetime

from core.emotion import (
    Emotion,
    build_emotion_update_messages,
    decay,
    parse_emotion_update,
    apply_delta,
    tone_hint,
)
from core.ports import JsonScorer
from core.store import Store

logger = logging.getLogger(__name__)

EMOTION_TIMEOUT_SECONDS = 0.8


class EmotionUpdater:
    def __init__(
        self,
        store: Store,
        scorer: JsonScorer,
        *,
        user_id: str = "owner",
        user_role: str = "learner",
        timeout_seconds: float = EMOTION_TIMEOUT_SECONDS,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._store = store
        self._scorer = scorer
        self._user_id = user_id
        self._user_role = user_role
        self._timeout = timeout_seconds
        self._now = now
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    @property
    def _key(self) -> tuple[str, str]:
        return (self._user_id, self._user_role)

    def _lock(self) -> asyncio.Lock:
        lock = self._locks.get(self._key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[self._key] = lock
        return lock

    def current(self) -> Emotion:
        row = self._store.emotion_state(
            self._user_id, self._user_role, now=self._now().isoformat(timespec="seconds")
        )
        return decay(
            Emotion(comfort=row["comfort"], energy=row["energy"]),
            row["updated_at"],
            self._now(),
        )

    def event_payload(self) -> dict[str, object]:
        state = self.current()
        return {
            "comfort": round(state.comfort, 3),
            "energy": round(state.energy, 3),
            "tone": tone_hint(state),
        }

    async def update(
        self, user_text: str, history: Sequence[tuple[str, str]] = ()
    ) -> Emotion:
        async with self._lock():
            base = self.current()

        system_prompt, user_prompt = build_emotion_update_messages(
            base, user_text, history
        )
        try:
            raw = await asyncio.wait_for(
                self._scorer.grade(system_prompt, user_prompt),
                timeout=self._timeout,
            )
            delta = parse_emotion_update(raw)
        except Exception as exc:  # 情绪层不能拖垮回复：超时/异常/非法 JSON 都降级
            logger.warning("emotion_update_failed: %s", exc)
            return self.current()

        if delta.intense:
            logger.info("emotion_intense reason=%s", delta.reason or "-")

        async with self._lock():
            now = self._now()
            row = self._store.emotion_state(
                self._user_id,
                self._user_role,
                now=now.isoformat(timespec="seconds"),
            )
            latest = decay(
                Emotion(comfort=row["comfort"], energy=row["energy"]),
                row["updated_at"],
                now,
            )
            state = apply_delta(latest, delta)
            self._store.save_emotion_state(
                self._user_id,
                self._user_role,
                state.comfort,
                state.energy,
                now.isoformat(timespec="seconds"),
            )
        return state
