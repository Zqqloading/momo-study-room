from __future__ import annotations

import json
import sqlite3

import pytest

from core.db import connect, init_schema
from core.models import ConceptState, SessionRecord, SessionResult
from core.ports import QuestionScore
from core.store import SessionAlreadyFinalized, Store

BANK_ROW = {
    "id": "agent-recall-1",
    "concept_id": "agent",
    "kind": "recall",
    "question_text": "用你自己的话说说 agent 是什么。",
    "rubric_json": {"levels": [0, 40, 70, 90, 100]},
    "source_url": "https://example.com/agent",
    "source_excerpt": "Agent 是能感知环境并自主采取行动的系统。",
}


def make_store() -> Store:
    conn = connect(":memory:")
    init_schema(conn)
    store = Store(conn)
    store.upsert_concept(ConceptState(id="agent", mastery=1, status="active"))
    return store


def add_question(store: Store, session_id: str = "s1") -> int:
    return store.add_question(
        session_id=session_id,
        question_bank_id="agent-recall-1",
        concept_id="agent",
        role="new",
        kind="recall",
        text="用你自己的话说说 agent 是什么。",
        rubric_json={"levels": [0, 40, 70, 90, 100]},
        source_url="https://example.com/agent",
        source_excerpt="Agent 是能感知环境并自主采取行动的系统。",
        created_at="2026-11-23T20:00:00",
    )


def record(session_id: str = "s1", status: str = "completed", score: float = 70.0) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        date="2026-11-23",
        kind="daily",
        status=status,
        started_at="2026-11-23T19:40:00",
        created_at="2026-11-23T20:00:00",
        concept_id="agent",
        input_mode="text",
        session_score=score,
    )


def test_import_question_bank_is_idempotent() -> None:
    store = make_store()
    try:
        assert store.import_question_bank([BANK_ROW]) == 1
        assert store.import_question_bank([BANK_ROW]) == 0
        row = store.bank_question("agent-recall-1")
        assert row is not None
        assert row["options_json"] is None
        assert row["source_url"] == "https://example.com/agent"
    finally:
        store.close()


def test_import_question_bank_updates_changed_content() -> None:
    store = make_store()
    try:
        assert store.import_question_bank([BANK_ROW]) == 1
        changed = dict(BANK_ROW)
        changed["rubric_json"] = {
            "levels": [0, 40, 70, 90, 100],
            "explanation": "针对选项的解释",
        }
        assert store.import_question_bank([changed]) == 1
        row = store.bank_question("agent-recall-1")
        assert row is not None
        assert "针对选项的解释" in row["rubric_json"]
    finally:
        store.close()


def test_import_question_bank_rejects_missing_source() -> None:
    store = make_store()
    try:
        bad = dict(BANK_ROW)
        bad["source_excerpt"] = ""
        try:
            store.import_question_bank([bad])
        except ValueError as exc:
            assert "source_excerpt" in str(exc)
        else:
            raise AssertionError("应拒绝没有摘录的题")
    finally:
        store.close()


def test_add_question_persists_provenance_fields() -> None:
    store = make_store()
    try:
        question_id = store.add_question(
            session_id="s1",
            question_bank_id=None,
            concept_id="agent",
            role="new",
            kind="apply",
            question_type="tradeoff",
            text="在预算有限时，你会先做完整版还是 MVP？为什么？",
            rubric_json={"levels": [0, 40, 70, 90, 100]},
            source_url="https://example.com/m",
            source_excerpt="MVP 把验证范围压到核心流程。",
            source_chunk_id="m-v1-child-002",
            generation_meta_json={"origin": "generated", "repair_count": 0},
            created_at="2026-11-25T10:00:00",
        )
        saved = store.question(question_id)
        assert saved is not None
        assert saved["question_type"] == "tradeoff"
        assert saved["source_chunk_id"] == "m-v1-child-002"
        assert json.loads(saved["generation_meta_json"]) == {
            "origin": "generated",
            "repair_count": 0,
        }
    finally:
        store.close()


def test_add_question_without_provenance_keeps_columns_null() -> None:
    store = make_store()
    try:
        question_id = add_question(store)
        saved = store.question(question_id)
        assert saved is not None
        assert saved["question_type"] is None
        assert saved["source_chunk_id"] is None
        assert saved["generation_meta_json"] is None
    finally:
        store.close()


def test_previous_question_texts_returns_recent_first() -> None:
    store = make_store()
    try:
        for index in range(3):
            store.add_question(
                session_id="s1",
                question_bank_id=None,
                concept_id="agent",
                role="new",
                kind="recall",
                text=f"第 {index} 题",
                rubric_json={},
                source_url="u",
                source_excerpt="e",
                created_at="t",
            )
        store.add_question(
            session_id="s1",
            question_bank_id=None,
            concept_id="other",
            role="new",
            kind="recall",
            text="别的概念",
            rubric_json={},
            source_url="u",
            source_excerpt="e",
            created_at="t",
        )

        assert store.previous_question_texts("agent", limit=2) == ["第 2 题", "第 1 题"]
        assert store.previous_question_texts("missing") == []
    finally:
        store.close()


def test_question_commit_then_finalize_updates_derived_state() -> None:
    store = make_store()
    try:
        question_id = add_question(store)
        store.save_answer(question_id, text="agent 是会自己决定下一步的程序", score=70, feedback="方向对")

        saved = store.question(question_id)
        assert saved is not None
        assert saved["score"] == 70
        assert saved["answer_text"].startswith("agent")

        result = SessionResult(
            session_id="s1",
            status="completed",
            session_score=70.0,
            scores=(QuestionScore(question_id=str(question_id), score=70, why="方向对"),),
            mastery_updates={"agent": 4},
            concept_id="agent",
            review_due_at="2026-11-24",
            review_started_at="2026-11-23",
        )
        store.finalize(record(), result)

        session = store.session("s1")
        assert session is not None
        assert session["status"] == "completed"
        assert session["session_score"] == 70.0

        concept = store.concept_state("agent")
        assert concept is not None
        assert concept.mastery == 4
        assert concept.review_due_at == "2026-11-24"
        assert concept.review_started_at == "2026-11-23"
        assert concept.last_seen == "2026-11-23"
    finally:
        store.close()


def test_finalize_rolls_back_on_constraint_failure() -> None:
    store = make_store()
    try:
        question_id = add_question(store)
        result = SessionResult(
            session_id="s1",
            status="completed",
            session_score=70.0,
            scores=(QuestionScore(question_id=str(question_id), score=70, why="方向对"),),
            mastery_updates={"agent": 99},  # CHECK 会失败
            concept_id="agent",
            review_due_at="2026-11-24",
            review_started_at="2026-11-23",
        )
        try:
            store.finalize(record(), result)
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("mastery 99 应被 CHECK 拒绝")

        assert store.session("s1") is None
        concept = store.concept_state("agent")
        assert concept is not None
        assert concept.mastery == 1
        assert concept.review_due_at is None
    finally:
        store.close()


def test_finalize_is_not_repeatable() -> None:
    store = make_store()
    try:
        question_id = add_question(store)
        result = SessionResult(
            session_id="s1",
            status="completed",
            session_score=80.0,
            scores=(QuestionScore(question_id=str(question_id), score=80, why="好"),),
            mastery_updates={"agent": 4},
            concept_id="agent",
        )
        store.finalize(record(score=80.0), result)

        try:
            store.finalize(record(score=80.0), result)
        except SessionAlreadyFinalized:
            pass
        else:
            raise AssertionError("重复结算应被拒绝")
    finally:
        store.close()


def test_due_reviews_only_returns_due_concepts() -> None:
    store = make_store()
    try:
        store.upsert_concept(ConceptState(id="due", review_due_at="2026-11-23"))
        store.upsert_concept(ConceptState(id="later", review_due_at="2026-11-25"))
        store.upsert_concept(ConceptState(id="none"))
        due = store.due_reviews("2026-11-24")
        assert [state.id for state in due] == ["due"]
    finally:
        store.close()


def test_import_question_bank_updates_and_deletes() -> None:
    store = make_store()
    try:
        assert store.import_question_bank([BANK_ROW]) == 1

        revised = dict(BANK_ROW)
        revised["question_text"] = "改过的题"
        assert store.import_question_bank([revised]) == 1
        row = store.bank_question("agent-recall-1")
        assert row is not None
        assert row["question_text"] == "改过的题"

        assert store.import_question_bank([], allow_empty=True) == 1
        assert store.bank_question("agent-recall-1") is None
    finally:
        store.close()


def test_import_question_bank_refuses_accidental_empty() -> None:
    store = make_store()
    try:
        assert store.import_question_bank([BANK_ROW]) == 1
        with pytest.raises(ValueError, match="allow_empty"):
            store.import_question_bank([])
        assert store.bank_question("agent-recall-1") is not None
    finally:
        store.close()


def test_import_question_bank_allows_empty_when_already_empty() -> None:
    store = make_store()
    try:
        assert store.import_question_bank([]) == 0
    finally:
        store.close()


def test_import_question_bank_keeps_session_question_history() -> None:
    store = make_store()
    try:
        assert store.import_question_bank([BANK_ROW]) == 1
        question_id = add_question(store)

        assert store.import_question_bank([], allow_empty=True) == 1

        row = store.question(question_id)
        assert row is not None
        assert row["question_bank_id"] == "agent-recall-1"
        assert row["question_text"] == "用你自己的话说说 agent 是什么。"
        assert store.bank_question("agent-recall-1") is None
    finally:
        store.close()


def test_import_question_bank_deletes_only_missing_ids() -> None:
    store = make_store()
    try:
        second = dict(BANK_ROW, id="agent-apply-1", kind="apply")
        assert store.import_question_bank([BANK_ROW, second]) == 2
        question_id = add_question(store)

        assert store.import_question_bank([second]) == 1

        assert store.bank_question("agent-recall-1") is None
        assert store.bank_question("agent-apply-1") is not None
        row = store.question(question_id)
        assert row is not None
        assert row["question_bank_id"] == "agent-recall-1"
    finally:
        store.close()


def test_upsert_concept_source_keeps_single_primary() -> None:
    store = make_store()
    try:
        store.upsert_concept_source(
            concept_id="agent", chunk_id="c1", excerpt="旧摘录", is_primary=True
        )
        store.upsert_concept_source(
            concept_id="agent", chunk_id="c2", excerpt="新摘录", is_primary=True
        )

        rows = store.conn.execute(
            "SELECT chunk_id, is_primary FROM concept_sources WHERE concept_id = 'agent'"
        ).fetchall()
        primaries = [row["chunk_id"] for row in rows if row["is_primary"]]
        assert primaries == ["c2"]
        assert store.concept_source_excerpt("agent") == "新摘录"
    finally:
        store.close()


def test_finalize_rejects_unknown_concept() -> None:
    store = make_store()
    try:
        question_id = add_question(store)
        result = SessionResult(
            session_id="s1",
            status="completed",
            session_score=70.0,
            scores=(QuestionScore(question_id=str(question_id), score=70, why="方向对"),),
            mastery_updates={"missing": 4},
            concept_id="missing",
        )
        with pytest.raises(ValueError, match="concept 不存在"):
            store.finalize(record(), result)

        assert store.session("s1") is None
        agent = store.concept_state("agent")
        assert agent is not None
        assert agent.mastery == 1
    finally:
        store.close()


def test_due_reviews_excludes_non_active() -> None:
    store = make_store()
    try:
        store.upsert_concept(ConceptState(id="due", review_due_at="2026-11-23", status="active"))
        store.upsert_concept(ConceptState(id="known", review_due_at="2026-11-23", status="known"))
        store.upsert_concept(ConceptState(id="skipped", review_due_at="2026-11-23", status="skipped"))
        store.upsert_concept(
            ConceptState(id="orphaned", review_due_at="2026-11-23", status="orphaned")
        )
        due = store.due_reviews("2026-11-24")
        assert [state.id for state in due] == ["due"]
    finally:
        store.close()


def test_pipeline_run_lifecycle() -> None:
    store = make_store()
    try:
        run_id = store.start_pipeline_run("ingest", "materials/agent-basics.md")
        running = store.conn.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert running["status"] == "running"
        assert running["started_at"]
        assert running["input"] == "materials/agent-basics.md"

        store.finish_pipeline_run(run_id, "succeeded", {"chunks": 8})

        done = store.conn.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert done["status"] == "succeeded"
        assert done["finished_at"]
        assert json.loads(done["stats_json"]) == {"chunks": 8}
        assert done["error"] is None
    finally:
        store.close()


def test_pipeline_run_partial_and_failed() -> None:
    store = make_store()
    try:
        partial = store.start_pipeline_run("reindex")
        store.finish_pipeline_run(partial, "partial", {"embedded": 6, "failed": 2})
        failed = store.start_pipeline_run("extract")
        store.finish_pipeline_run(failed, "failed", error="deepseek timeout")

        partial_row = store.conn.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (partial,)
        ).fetchone()
        failed_row = store.conn.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (failed,)
        ).fetchone()
        assert partial_row["status"] == "partial"
        assert failed_row["status"] == "failed"
        assert failed_row["error"] == "deepseek timeout"
        assert partial_row["input"] is None
    finally:
        store.close()


def test_start_pipeline_run_aborts_stale_same_kind() -> None:
    store = make_store()
    try:
        stale = store.start_pipeline_run("reindex")
        other = store.start_pipeline_run("ingest")
        fresh = store.start_pipeline_run("reindex")

        stale_row = store.conn.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (stale,)
        ).fetchone()
        other_row = store.conn.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (other,)
        ).fetchone()
        fresh_row = store.conn.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (fresh,)
        ).fetchone()

        assert stale_row["status"] == "failed"
        assert stale_row["error"] == "aborted"
        assert stale_row["finished_at"]
        assert other_row["status"] == "running"
        assert fresh_row["status"] == "running"
    finally:
        store.close()


def _add_scored(
    store: Store,
    session_id: str,
    *,
    score: int | None = 70,
    role: str = "new",
    concept_id: str = "agent",
    created_at: str = "2026-11-20T20:01:00",
) -> int:
    question_id = store.add_question(
        session_id=session_id,
        question_bank_id=None,
        concept_id=concept_id,
        role=role,
        kind="apply",
        text="题",
        rubric_json={},
        source_url="fixture://a",
        source_excerpt="出处",
        created_at=created_at,
    )
    if score is not None:
        store.save_answer(question_id, text="答", score=score, feedback="反馈")
    return question_id


def _insert_session(
    store: Store,
    session_id: str,
    date: str,
    *,
    status: str = "completed",
    concept_id: str = "agent",
) -> None:
    store.conn.execute(
        """
        INSERT INTO sessions
          (id, date, concept_id, kind, status, started_at, input_mode, created_at)
        VALUES (?, ?, ?, 'daily', ?, ?, 'text', ?)
        """,
        (session_id, date, concept_id, status, f"{date}T20:00:00", f"{date}T20:20:00"),
    )
    store.conn.commit()


def test_latest_concept_assessments_uses_latest_scored_session() -> None:
    store = make_store()
    try:
        store.start_agent_session(
            session_id="old",
            kind="daily",
            date="2026-11-20",
            started_at="2026-11-20T20:00:00",
        )
        _add_scored(store, "old", score=60, created_at="2026-11-20T20:01:00")
        _insert_session(store, "old", "2026-11-20")

        store.start_agent_session(
            session_id="new",
            kind="daily",
            date="2026-11-21",
            started_at="2026-11-21T20:00:00",
        )
        _add_scored(store, "new", score=70, created_at="2026-11-21T20:01:00")
        _add_scored(
            store,
            "new",
            score=90,
            role="review",
            created_at="2026-11-21T20:02:00",
        )
        _insert_session(store, "new", "2026-11-21", status="partial")

        latest = store.latest_concept_assessments(["agent"])
        assert latest["agent"].session_id == "new"
        assert latest["agent"].date == "2026-11-21"
        assert latest["agent"].avg_score == 80.0
        assert latest["agent"].min_score == 70.0
        assert latest["agent"].scored == 2
    finally:
        store.close()


def test_latest_concept_assessments_skips_unscored_and_uses_agent_date() -> None:
    store = make_store()
    try:
        store.start_agent_session(
            session_id="scored",
            kind="daily",
            date="2026-11-20",
            started_at="2026-11-20T20:00:00",
        )
        _add_scored(store, "scored", score=40, created_at="2026-11-20T20:01:00")

        store.start_agent_session(
            session_id="unscored",
            kind="daily",
            date="2026-11-21",
            started_at="2026-11-21T20:00:00",
        )
        _add_scored(store, "unscored", score=None, created_at="2026-11-21T20:01:00")
        store.conn.execute(
            "UPDATE agent_sessions SET status = 'abandoned' WHERE session_id = ?",
            ("unscored",),
        )
        store.conn.commit()

        latest = store.latest_concept_assessments(["agent"])
        assert latest["agent"].session_id == "scored"
        assert latest["agent"].date == "2026-11-20"
        assert latest["agent"].avg_score == 40.0
        assert latest["agent"].min_score == 40.0
    finally:
        store.close()


def test_latest_concept_assessments_prefers_sessions_date_and_filters() -> None:
    store = make_store()
    try:
        store.upsert_concept(ConceptState(id="other", mastery=0, status="active"))
        store.start_agent_session(
            session_id="finalized",
            kind="daily",
            date="2026-11-19",
            started_at="2026-11-19T20:00:00",
        )
        _add_scored(store, "finalized", score=90, created_at="2026-11-19T20:01:00")
        _insert_session(store, "finalized", "2026-11-22")

        store.start_agent_session(
            session_id="abandoned",
            kind="daily",
            date="2026-11-21",
            started_at="2026-11-21T20:00:00",
        )
        _add_scored(store, "abandoned", score=40, created_at="2026-11-21T20:01:00")
        _add_scored(
            store,
            "abandoned",
            score=100,
            concept_id="other",
            created_at="2026-11-21T20:02:00",
        )

        latest = store.latest_concept_assessments(["agent"])
        assert latest["agent"].session_id == "finalized"
        assert latest["agent"].date == "2026-11-22"
        assert latest["agent"].avg_score == 90.0
        assert "other" not in latest

        assert store.latest_concept_assessments([]) == {}
        assert store.latest_concept_assessments(None)["other"].session_id == "abandoned"
    finally:
        store.close()
