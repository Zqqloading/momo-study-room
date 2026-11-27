"""v0 规划器：只从 active 概念里选下一个新概念。

解锁条件：所有前置 concept 的 mastery >= 3，或状态为 skipped。
排序：难度低优先，同级按最久没见（last_seen 为空视为最久）。
"""

from __future__ import annotations

from .concepts import Concept
from .models import ConceptState

UNLOCK_MASTERY = 3


class Planner:
    def __init__(self, concepts: list[Concept]) -> None:
        self._concepts = {concept.id: concept for concept in concepts}

    def unlocked(self, concept_id: str, states: dict[str, ConceptState]) -> bool:
        concept = self._concepts.get(concept_id)
        if concept is None:
            return False
        for prerequisite in concept.prerequisites:
            state = states.get(prerequisite)
            if state is None:
                return False
            if state.mastery < UNLOCK_MASTERY and state.status != "skipped":
                return False
        return True

    def next_concept(
        self, states: list[ConceptState], today: str | None = None
    ) -> ConceptState | None:
        by_id = {state.id: state for state in states}
        candidates = [
            state
            for state in states
            if state.status == "active"
            and state.id in self._concepts
            and self.unlocked(state.id, by_id)
        ]
        if not candidates:
            return None

        def sort_key(state: ConceptState) -> tuple[int, str, str]:
            concept = self._concepts[state.id]
            # last_seen 为空表示从未学过，排在最前；日期字符串可直接比较。
            return (concept.difficulty, state.last_seen or "", state.id)

        return min(candidates, key=sort_key)
