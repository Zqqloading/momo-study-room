from __future__ import annotations

from core.concepts import Concept, Source
from core.models import ConceptState
from core.planner import Planner


def concept(concept_id: str, difficulty: int, prerequisites: tuple[str, ...] = ()) -> Concept:
    return Concept(
        id=concept_id,
        name=concept_id,
        aliases=(),
        plain_def=f"{concept_id} 的定义",
        difficulty=difficulty,
        prerequisites=prerequisites,
        source=Source(url="https://example.com", excerpt="摘录"),
    )


def state(concept_id: str, mastery: int = 0, status: str = "active", last_seen: str | None = None) -> ConceptState:
    return ConceptState(id=concept_id, mastery=mastery, status=status, last_seen=last_seen)


def make_planner() -> Planner:
    return Planner(
        [
            concept("agent", 1),
            concept("tool-calling", 2, ("agent",)),
            concept("memory", 2, ("agent",)),
        ]
    )


def test_prerequisite_still_selected_when_not_mastered() -> None:
    planner = make_planner()
    picked = planner.next_concept([state("agent", mastery=2), state("tool-calling")])
    assert picked is not None
    assert picked.id == "agent"


def test_locked_when_prerequisite_state_missing() -> None:
    planner = make_planner()
    assert planner.next_concept([state("tool-calling")]) is None


def test_skipped_prerequisite_unlocks() -> None:
    planner = make_planner()
    picked = planner.next_concept(
        [state("agent", status="skipped"), state("tool-calling")]
    )
    assert picked is not None
    assert picked.id == "tool-calling"


def test_known_prerequisite_unlocks_via_mastery() -> None:
    planner = make_planner()
    picked = planner.next_concept(
        [state("agent", mastery=5, status="known"), state("memory")]
    )
    assert picked is not None
    assert picked.id == "memory"


def test_prefers_lower_difficulty_then_longest_unseen() -> None:
    planner = make_planner()
    picked = planner.next_concept(
        [
            state("agent", mastery=5, status="known"),
            state("tool-calling", last_seen="2026-11-10"),
            state("memory", last_seen=None),
        ]
    )
    assert picked is not None
    assert picked.id == "memory"


def test_ignores_proposed_and_orphaned() -> None:
    planner = make_planner()
    assert (
        planner.next_concept(
            [
                state("agent", mastery=5, status="known"),
                state("tool-calling", status="proposed"),
                state("memory", status="orphaned"),
            ]
        )
        is None
    )
