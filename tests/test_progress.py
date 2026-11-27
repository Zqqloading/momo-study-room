from __future__ import annotations

from dataclasses import replace

from core.concepts import load_concepts
from core.models import ConceptAssessment
from core.progress import build_overview
from support import CONCEPTS_PATH, make_coach

TODAY = "2026-11-23"


def _add_session(
    store,
    session_id: str,
    *,
    date: str,
    kind: str,
    status: str = "completed",
    score: float | None = 70.0,
    concept_ids: tuple[str, ...] = (),
    created_at: str,
) -> None:
    store.conn.execute(
        """
        INSERT INTO sessions
          (id, date, concept_id, kind, status, started_at, input_mode,
           session_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'text', ?, ?)
        """,
        (
            session_id,
            date,
            concept_ids[0] if kind == "daily" and concept_ids else None,
            kind,
            status,
            f"{date}T20:00:00",
            score,
            created_at,
        ),
    )
    store.conn.commit()
    for concept_id in concept_ids:
        store.add_question(
            session_id=session_id,
            question_bank_id=None,
            concept_id=concept_id,
            role="new" if kind == "daily" else "review",
            kind="apply",
            text="题",
            rubric_json={},
            source_url="fixture://unit",
            source_excerpt="出处",
            created_at=f"{date}T20:05:00",
        )


def test_overview_stats_distribution_and_sorting() -> None:
    store, _, _ = make_coach()
    try:
        agent_loop = store.concept_state("agent-loop")
        tool_use = store.concept_state("tool-use")
        memory = store.concept_state("memory")
        assert agent_loop and tool_use and memory
        store.upsert_concept(
            replace(
                agent_loop,
                mastery=3,
                last_seen="2026-11-20",
                review_due_at="2026-11-22",
            )
        )
        store.upsert_concept(
            replace(
                tool_use,
                mastery=1,
                last_seen="2026-11-21",
                review_due_at="2026-11-23",
            )
        )
        store.upsert_concept(replace(memory, mastery=0, last_seen=None))

        overview = build_overview(
            load_concepts(CONCEPTS_PATH),
            store.concept_states(),
            [],
            TODAY,
        )

        assert overview.stats.active == 3
        assert overview.stats.avg_mastery == 1.3
        assert overview.stats.due == 2
        assert overview.stats.overdue == 1
        assert overview.stats.weak == 1
        counts = {item.mastery: item.count for item in overview.stats.distribution}
        assert counts == {0: 1, 1: 1, 2: 0, 3: 1, 4: 0, 5: 0}
        assert [item.id for item in overview.concepts] == [
            "memory",
            "tool-use",
            "agent-loop",
        ]
        labels = {item.id: item.mastery_label for item in overview.concepts}
        assert labels["memory"] == "未掌握"
        assert labels["tool-use"] == "初识"
        assert labels["agent-loop"] == "基本掌握"
        assert overview.concepts[0].overdue_days == 0
        assert overview.concepts[1].overdue_days == 0
        assert overview.concepts[2].overdue_days == 1
    finally:
        store.close()


def test_overview_only_lists_active_and_counts_other_statuses() -> None:
    store, _, _ = make_coach()
    try:
        agent_loop = store.concept_state("agent-loop")
        memory = store.concept_state("memory")
        assert agent_loop and memory
        store.upsert_concept(replace(agent_loop, status="known"))
        store.upsert_concept(replace(memory, status="skipped"))

        overview = build_overview(
            load_concepts(CONCEPTS_PATH),
            store.concept_states(),
            [],
            TODAY,
        )
        assert overview.stats.active == 1
        assert overview.stats.known == 1
        assert overview.stats.skipped == 1
        assert [item.id for item in overview.concepts] == ["tool-use"]
    finally:
        store.close()


def test_overview_empty_is_safe() -> None:
    store, _, _ = make_coach()
    try:
        store.conn.execute("DELETE FROM concepts")
        store.conn.commit()
        overview = build_overview(
            load_concepts(CONCEPTS_PATH),
            store.concept_states(),
            [],
            TODAY,
        )
        assert overview.stats.active == 0
        assert overview.stats.avg_mastery is None
        assert overview.stats.due == 0
        assert overview.stats.overdue == 0
        assert overview.stats.weak == 0
        assert overview.concepts == ()
        assert overview.recent_units == ()
        assert all(item.count == 0 for item in overview.stats.distribution)
    finally:
        store.close()


def test_overview_recent_units_names_and_limit() -> None:
    store, _, _ = make_coach()
    try:
        for index in range(1, 7):
            _add_session(
                store,
                f"s{index}",
                date="2026-11-20",
                kind="daily" if index != 6 else "review",
                concept_ids=("agent-loop", "tool-use")
                if index != 6
                else ("tool-use",),
                created_at=f"2026-11-23T20:00:0{index}",
            )

        units = store.recent_units()
        assert len(units) == 5
        assert [unit["session_id"] for unit in units] == ["s6", "s5", "s4", "s3", "s2"]

        overview = build_overview(
            load_concepts(CONCEPTS_PATH),
            store.concept_states(),
            units,
            TODAY,
        )
        assert len(overview.recent_units) == 5
        assert overview.recent_units[0].kind == "review"
        assert overview.recent_units[0].concept_names == ("工具调用",)
        assert set(overview.recent_units[1].concept_names) == {"Agent 循环", "工具调用"}
    finally:
        store.close()


def test_overview_future_due_is_not_counted_and_unseen_is_not_weak() -> None:
    store, _, _ = make_coach()
    try:
        agent_loop = store.concept_state("agent-loop")
        tool_use = store.concept_state("tool-use")
        assert agent_loop and tool_use
        store.upsert_concept(
            replace(agent_loop, mastery=0, last_seen=None, review_due_at="2026-11-24")
        )
        store.upsert_concept(
            replace(tool_use, mastery=1, last_seen="2026-11-20", review_due_at=None)
        )

        overview = build_overview(
            load_concepts(CONCEPTS_PATH),
            store.concept_states(),
            [],
            TODAY,
        )
        assert overview.stats.due == 0
        assert overview.stats.overdue == 0
        assert overview.stats.weak == 1
    finally:
        store.close()


def test_overview_labels_do_not_write_mastery() -> None:
    store, _, _ = make_coach()
    try:
        tool_use = store.concept_state("tool-use")
        assert tool_use
        store.upsert_concept(replace(tool_use, mastery=4))
        before = store.concept_states()
        overview = build_overview(
            load_concepts(CONCEPTS_PATH),
            before,
            [],
            TODAY,
        )
        assert {
            item.id: item.mastery_label for item in overview.concepts
        }["tool-use"] == "熟练"
        assert store.concept_states() == before
    finally:
        store.close()


def test_overview_weak_includes_recent_miss_without_double_count() -> None:
    store, _, _ = make_coach()
    try:
        states = store.concept_states()
        agent_loop = next(state for state in states if state.id == "agent-loop")
        tool_use = next(state for state in states if state.id == "tool-use")
        store.upsert_concept(
            replace(agent_loop, mastery=4, last_seen="2026-11-20")
        )
        store.upsert_concept(
            replace(tool_use, mastery=1, last_seen="2026-11-20")
        )
        states = store.concept_states()

        assessments = {
            "agent-loop": ConceptAssessment(
                concept_id="agent-loop",
                date=TODAY,
                session_id="s1",
                avg_score=40,
                min_score=40,
                scored=1,
            ),
            "tool-use": ConceptAssessment(
                concept_id="tool-use",
                date=TODAY,
                session_id="s2",
                avg_score=90,
                min_score=90,
                scored=1,
            ),
        }
        overview = build_overview(
            load_concepts(CONCEPTS_PATH),
            states,
            [],
            TODAY,
            assessments,
        )
        assert overview.stats.weak == 2

        without = build_overview(
            load_concepts(CONCEPTS_PATH),
            states,
            [],
            TODAY,
        )
        assert without.stats.weak == 1
    finally:
        store.close()
