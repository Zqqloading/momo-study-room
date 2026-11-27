from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core.concepts import load_concepts
from core.models import ConceptAssessment, ConceptState
from core.selection import select_topic, stable_pick
from support import CONCEPTS_PATH

TODAY = "2026-11-23"
ROOT = Path(__file__).resolve().parent.parent
CONCEPTS = load_concepts(CONCEPTS_PATH)


def state(
    concept_id: str,
    *,
    mastery: int = 0,
    last_seen: str | None = None,
    status: str = "active",
) -> ConceptState:
    return ConceptState(
        id=concept_id,
        mastery=mastery,
        status=status,
        last_seen=last_seen,
    )


def assessment(
    concept_id: str,
    *,
    date: str,
    avg: float,
    min_score: float,
    scored: int = 1,
) -> ConceptAssessment:
    return ConceptAssessment(
        concept_id=concept_id,
        date=date,
        session_id=f"s-{concept_id}-{date}",
        avg_score=avg,
        min_score=min_score,
        scored=scored,
    )


def test_recent_miss_wins_over_mastery() -> None:
    states = [
        state("agent-loop", mastery=5, last_seen="2026-11-20"),
        state("tool-use", mastery=1, last_seen="2026-11-20"),
        state("memory", mastery=0, last_seen="2026-11-20"),
    ]
    assessments = {
        "agent-loop": assessment("agent-loop", date="2026-11-22", avg=40, min_score=40),
    }

    selection = select_topic(states, assessments, CONCEPTS, TODAY)

    assert selection is not None
    assert selection.state.id == "agent-loop"
    assert selection.reason_kind == "recent_miss"
    assert selection.assessment is not None
    assert selection.assessment.min_score == 40


def test_recent_miss_picks_most_recent_then_worst() -> None:
    states = [
        state("agent-loop", mastery=3, last_seen="2026-11-20"),
        state("tool-use", mastery=3, last_seen="2026-11-20"),
    ]
    assessments = {
        "agent-loop": assessment("agent-loop", date="2026-11-21", avg=70, min_score=60),
        "tool-use": assessment("tool-use", date="2026-11-22", avg=55, min_score=40),
    }

    selection = select_topic(states, assessments, CONCEPTS, TODAY)
    assert selection is not None
    assert selection.state.id == "tool-use"
    assert selection.reason_kind == "recent_miss"

    same_day = {
        "agent-loop": assessment("agent-loop", date="2026-11-22", avg=50, min_score=50),
        "tool-use": assessment("tool-use", date="2026-11-22", avg=30, min_score=30),
    }
    selection = select_topic(states, same_day, CONCEPTS, TODAY)
    assert selection is not None
    assert selection.state.id == "tool-use"


def test_lowest_mastery_skips_locked_unseen() -> None:
    states = [
        state("agent-loop", mastery=2, last_seen="2026-11-20"),
        state("tool-use", mastery=1, last_seen="2026-11-20"),
        state("memory", mastery=0, last_seen=None),
    ]

    selection = select_topic(states, {}, CONCEPTS, TODAY)

    assert selection is not None
    assert selection.state.id == "tool-use"
    assert selection.reason_kind == "lowest_mastery"


def test_all_unseen_unlocked_uses_stable_random() -> None:
    states = [
        state("agent-loop", status="skipped"),
        state("tool-use", mastery=0),
        state("memory", mastery=0),
    ]

    first = select_topic(states, {}, CONCEPTS, TODAY)
    second = select_topic(states, {}, CONCEPTS, TODAY)

    assert first is not None and second is not None
    assert first == second
    assert first.reason_kind == "no_signal"
    assert first.state.id in {"tool-use", "memory"}


def test_unseen_locked_concept_is_not_candidate() -> None:
    states = [
        state("agent-loop", mastery=0),
        state("tool-use", mastery=0),
        state("memory", mastery=0),
    ]

    selection = select_topic(states, {}, CONCEPTS, TODAY)

    assert selection is not None
    assert selection.state.id == "agent-loop"
    assert selection.reason_kind == "no_signal"


def test_no_candidates_returns_none() -> None:
    all_known = [state(item.id, status="known") for item in CONCEPTS]
    assert select_topic(all_known, {}, CONCEPTS, TODAY) is None

    locked = [
        state("agent-loop", status="known"),
        state("tool-use", mastery=0),
        state("memory", mastery=0),
    ]
    assert select_topic(locked, {}, CONCEPTS, TODAY) is None


def test_stable_pick_is_cross_process() -> None:
    expected = stable_pick(["agent-loop", "tool-use", "memory"], TODAY)
    code = (
        "from core.selection import stable_pick; "
        f"print(stable_pick(['memory','agent-loop','tool-use'], '{TODAY}'))"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == expected
