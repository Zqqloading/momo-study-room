"""用户记忆的读取路径：单元开场 top 3 + 自由对话显式回忆。"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from datetime import datetime

from core.memory import (
    current_strength,
    extract_clue,
    recall_update,
    render_opening,
)
from core.store import Store

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(
        self,
        store: Store,
        *,
        user_id: str = "owner",
        clock: Callable[[], datetime] = datetime.now,
        rng: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._store = store
        self._user_id = user_id
        self._clock = clock
        self._rng = rng

    def opening_block(self, *, max_chars: int = 300) -> str:
        """取 top 3 并更新回忆；选择和更新在同一个短事务里。"""
        now = self._clock()
        with self._store.transaction():
            rendered = render_opening(
                self._store.user_memories(self._user_id),
                now,
                max_chars=max_chars,
            )
            for memory in rendered.selected:
                updates = recall_update(
                    memory, now, strong=False, rng=self._rng
                )
                self._store.update_memory_recall(memory["id"], **updates)
        return rendered.text

    def recall(self, text: str) -> str | None:
        """None = 没有回忆意图；"" = 有意图但没命中；否则返回记忆块正文。"""
        clue = extract_clue(text)
        if not clue:
            return None
        now = self._clock()
        with self._store.transaction():
            rows = self._store.search_user_memories(
                self._user_id, clue, limit=3
            )
            if not rows:
                return ""
            rows.sort(
                key=lambda row: (
                    -float(row.get("score") or 0.0),
                    -current_strength(row, now),
                    str(row.get("last_recalled_at") or ""),
                    int(row.get("id") or 0),
                )
            )
            selected = rows[:3]
            for memory in selected:
                updates = recall_update(
                    memory, now, strong=True, rng=self._rng
                )
                self._store.update_memory_recall(memory["id"], **updates)
        return "\n".join(
            f"- {str(memory['text']).strip()}" for memory in selected
        )
