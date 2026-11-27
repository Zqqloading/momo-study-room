from __future__ import annotations

import pytest

from core.admin_tasks import (
    TaskParamError,
    append_log,
    create_task,
    finish_task,
    get_task,
    list_tasks,
    mark_running,
    recover_tasks,
    redact_log,
    update_progress,
    queued_task_ids,
)
from core.db import connect, init_schema


def make_conn():
    conn = connect(":memory:")
    init_schema(conn)
    return conn


def test_create_task_normalizes_and_persists() -> None:
    conn = make_conn()
    try:
        task, created = create_task(
            conn, kind="rebuild", params={"fts_only": True}
        )
        assert created is True
        assert task["kind"] == "rebuild"
        assert task["status"] == "queued"
        assert task["params"] == {
            "fts_only": True,
            "prune": False,
            "model": "text-embedding-v4",
            "dim": 1024,
        }
        loaded = get_task(conn, task["task_id"])
        assert loaded is not None
        assert loaded["task_id"] == task["task_id"]
    finally:
        conn.close()


def test_duplicate_active_task_returns_existing() -> None:
    conn = make_conn()
    try:
        first, created = create_task(
            conn, kind="rebuild", params={"fts_only": True}
        )
        second, created_again = create_task(
            conn, kind="rebuild", params={"fts_only": True}
        )
        assert created is True
        assert created_again is False
        assert second["task_id"] == first["task_id"]
        assert list_tasks(conn)["total"] == 1
    finally:
        conn.close()


def test_invalid_params_are_rejected() -> None:
    conn = make_conn()
    try:
        with pytest.raises(TaskParamError) as outside:
            create_task(
                conn, kind="ingest", params={"path": "docs/x.md"}
            )
        assert outside.value.field == "path"

        with pytest.raises(TaskParamError) as traversal:
            create_task(
                conn, kind="ingest", params={"path": "materials/../x.md"}
            )
        assert traversal.value.field == "path"

        with pytest.raises(TaskParamError) as confirm:
            create_task(
                conn,
                kind="ingest",
                params={"path": "materials/x.md", "confirm": True},
            )
        assert confirm.value.field == "confirm"

        with pytest.raises(TaskParamError) as dim:
            create_task(conn, kind="rebuild", params={"dim": 0})
        assert dim.value.field == "dim"

        with pytest.raises(TaskParamError) as suite:
            create_task(conn, kind="evaluate", params={"suites": ["nope"]})
        assert suite.value.field == "suites"

        with pytest.raises(TaskParamError) as unknown:
            create_task(conn, kind="rebuild", params={"nope": True})
        assert unknown.value.field == "nope"
    finally:
        conn.close()


def test_task_lifecycle_progress_logs_and_result() -> None:
    conn = make_conn()
    try:
        task, _ = create_task(
            conn, kind="ingest", params={"path": "materials/x.md", "dry_run": True}
        )
        task_id = task["task_id"]
        mark_running(conn, task_id)
        update_progress(
            conn,
            task_id,
            {"phase": "ingest", "current": 1, "total": 2, "message": "half"},
        )
        append_log(conn, task_id, "MIMO_API_KEY=secret-value\nworking\n")
        finish_task(conn, task_id, "succeeded", result={"ok": True})
        loaded = get_task(conn, task_id)
        assert loaded is not None
        assert loaded["status"] == "succeeded"
        assert loaded["result"] == {"ok": True}
        assert loaded["progress"]["phase"] == "ingest"
        assert loaded["log_tail"] == ["MIMO_API_KEY=***", "working"]
        assert loaded["finished_at"]
    finally:
        conn.close()


def test_log_is_redacted_and_capped() -> None:
    assert redact_log("Authorization: Bearer abcdefghijklmnop") == (
        "Authorization: Bearer ***"
    )
    conn = make_conn()
    try:
        task, _ = create_task(
            conn, kind="ingest", params={"path": "materials/x.md"}
        )
        append_log(conn, task["task_id"], "x" * (70 * 1024))
        row = conn.execute(
            "SELECT length(log_text) FROM admin_tasks WHERE id = ?",
            (task["task_id"],),
        ).fetchone()
        assert row[0] <= 64 * 1024
    finally:
        conn.close()


def test_recover_marks_running_failed_and_keeps_queued() -> None:
    conn = make_conn()
    try:
        running, _ = create_task(
            conn, kind="ingest", params={"path": "materials/a.md"}
        )
        queued, _ = create_task(
            conn, kind="ingest", params={"path": "materials/b.md"}
        )
        mark_running(conn, running["task_id"])
        assert recover_tasks(conn) == 1
        assert get_task(conn, running["task_id"])["status"] == "failed"
        assert get_task(conn, running["task_id"])["error"] == (
            "server restarted before completion"
        )
        assert queued_task_ids(conn) == [queued["task_id"]]
    finally:
        conn.close()


def test_list_filters_and_pagination() -> None:
    conn = make_conn()
    try:
        for index in range(3):
            create_task(
                conn, kind="ingest", params={"path": f"materials/{index}.md"}
            )
        page = list_tasks(conn, page=1, per_page=2)
        assert page["total"] == 3
        assert len(page["data"]) == 2
        assert list_tasks(conn, kind="rebuild")["total"] == 0
        assert list_tasks(conn, status="queued")["total"] == 3
    finally:
        conn.close()


def test_list_tasks_ids_sort_and_invalid_sort() -> None:
    conn = make_conn()
    try:
        first, _ = create_task(
            conn, kind="ingest", params={"path": "materials/a.md"}
        )
        create_task(conn, kind="rebuild", params={"fts_only": True})
        selected = list_tasks(conn, ids=first["task_id"])
        assert selected["total"] == 1
        assert selected["data"][0]["task_id"] == first["task_id"]
        assert list_tasks(conn, sort="status", order="asc")["total"] == 2
        with pytest.raises(TaskParamError):
            list_tasks(conn, sort="bad")
    finally:
        conn.close()
