from __future__ import annotations

import asyncio
from pathlib import Path

from bff.admin_task_runner import TaskRunner
from bff.config import load_settings
from core.admin_tasks import create_task, get_task, mark_running
from core.db import connect, init_schema
from core.store import Store


def make_env(tmp_path) -> dict[str, str]:
    return {
        "PROVIDER_MODE": "fake",
        "DB_PATH": str(tmp_path / "app.db"),
        "DATA_DIR": str(tmp_path / "data"),
        "CONTENT_DIR": str(tmp_path),
    }


def make_store(tmp_path) -> Store:
    store = Store(connect(tmp_path / "app.db"))
    init_schema(store.conn)
    return store


async def fake_runner(args, on_line, timeout):
    module = args[1]
    lines: list[str] = []

    def emit(line: str) -> None:
        lines.append(line)
        on_line(line)

    if module == "core.ingest":
        if "--dry-run" in args:
            emit("dry run ok")
            return 0, lines
        emit("pipeline_run_id=11")
        emit("materials/x.md  material=m v2 parent=1 child=2")
        return 0, lines

    if module == "core.extract":
        emit("pipeline_run_id=12")
        emit(
            "data/candidates/m.candidates.json  "
            "candidates=3 warnings=0 failures=0"
        )
        return 0, lines

    if module == "core.reindex":
        emit("pipeline_run_id=13")
        emit("fts=10 embedded=4 failed=0 missing_before=4")
        return 0, lines

    if module == "bff.probe":
        emit("probe ok")
        return 0, lines

    if module == "bff.asr_eval":
        emit("还没有录音：把文件放到 audio/")
        return 2, lines

    emit("boom")
    return 1, lines


def test_ingest_dry_run_stops_before_extract(tmp_path) -> None:
    store = make_store(tmp_path)
    try:
        runner = TaskRunner(
            store, load_settings(make_env(tmp_path)), command_runner=fake_runner
        )
        task, _ = create_task(
            store.conn,
            kind="ingest",
            params={"path": "materials/x.md", "dry_run": True},
        )
        asyncio.run(runner.execute(task["task_id"]))
        loaded = get_task(store.conn, task["task_id"])
        assert loaded is not None
        assert loaded["status"] == "succeeded"
        assert loaded["result"]["dry_run"] is True
        assert loaded["result"]["pipeline_run_ids"] == []
    finally:
        store.close()


def test_ingest_with_extract_ends_awaiting_review(tmp_path) -> None:
    store = make_store(tmp_path)
    try:
        runner = TaskRunner(
            store, load_settings(make_env(tmp_path)), command_runner=fake_runner
        )
        task, _ = create_task(
            store.conn,
            kind="ingest",
            params={
                "path": "materials/x.md",
                "extract": True,
                "emit_chunks": True,
            },
        )
        asyncio.run(runner.execute(task["task_id"]))
        loaded = get_task(store.conn, task["task_id"])
        assert loaded is not None
        assert loaded["status"] == "awaiting_review"
        assert loaded["result"]["candidates_path"].endswith(".candidates.json")
        assert loaded["result"]["candidates"] == 3
        assert loaded["result"]["pipeline_run_ids"] == [11, 12]
    finally:
        store.close()


def test_rebuild_result_and_run_ids(tmp_path) -> None:
    store = make_store(tmp_path)
    try:
        runner = TaskRunner(
            store, load_settings(make_env(tmp_path)), command_runner=fake_runner
        )
        task, _ = create_task(
            store.conn, kind="rebuild", params={"fts_only": True}
        )
        asyncio.run(runner.execute(task["task_id"]))
        loaded = get_task(store.conn, task["task_id"])
        assert loaded is not None
        assert loaded["status"] == "succeeded"
        assert loaded["result"] == {
            "fts_rows": 10,
            "embedded": 4,
            "embeddings_added": 4,
            "embeddings_pruned": None,
            "fts_pruned": None,
            "missing_before": 4,
            "pipeline_run_ids": [13],
        }
    finally:
        store.close()


def test_evaluate_skips_missing_inputs_and_passes_probe(tmp_path) -> None:
    store = make_store(tmp_path)
    try:
        runner = TaskRunner(
            store, load_settings(make_env(tmp_path)), command_runner=fake_runner
        )
        skipped, _ = create_task(
            store.conn,
            kind="evaluate",
            params={"suites": ["questions", "asr", "agent"]},
        )
        asyncio.run(runner.execute(skipped["task_id"]))
        skipped_task = get_task(store.conn, skipped["task_id"])
        assert skipped_task is not None
        assert skipped_task["status"] == "succeeded"
        assert skipped_task["result"]["passed"] is False
        assert [item["status"] for item in skipped_task["result"]["items"]] == [
            "skipped",
            "skipped",
            "skipped",
        ]

        passed, _ = create_task(
            store.conn, kind="evaluate", params={"suites": ["probe"]}
        )
        asyncio.run(runner.execute(passed["task_id"]))
        passed_task = get_task(store.conn, passed["task_id"])
        assert passed_task is not None
        assert passed_task["result"]["passed"] is True
        assert passed_task["result"]["items"][0]["status"] == "succeeded"
    finally:
        store.close()


def test_command_failure_marks_task_failed(tmp_path) -> None:
    store = make_store(tmp_path)
    try:
        async def failing(args, on_line, timeout):
            on_line("boom")
            return 1, ["boom"]

        runner = TaskRunner(
            store, load_settings(make_env(tmp_path)), command_runner=failing
        )
        task, _ = create_task(
            store.conn, kind="ingest", params={"path": "materials/x.md"}
        )
        asyncio.run(runner.execute(task["task_id"]))
        loaded = get_task(store.conn, task["task_id"])
        assert loaded is not None
        assert loaded["status"] == "failed"
        assert "exit 1" in loaded["error"]
    finally:
        store.close()


def test_start_and_submit_worker(tmp_path) -> None:
    store = make_store(tmp_path)
    try:
        runner = TaskRunner(
            store, load_settings(make_env(tmp_path)), command_runner=fake_runner
        )

        async def scenario() -> None:
            await runner.start()
            task, _ = create_task(
                store.conn, kind="rebuild", params={"fts_only": True}
            )
            await runner.submit(task["task_id"])
            for _ in range(50):
                loaded = get_task(store.conn, task["task_id"])
                if loaded and loaded["status"] == "succeeded":
                    break
                await asyncio.sleep(0.02)
            else:
                raise AssertionError("任务没有在等待时间内完成")
            await runner.stop()

        asyncio.run(scenario())
    finally:
        store.close()


def test_recover_running_task_on_start(tmp_path) -> None:
    store = make_store(tmp_path)
    try:
        task, _ = create_task(
            store.conn, kind="rebuild", params={"fts_only": True}
        )
        mark_running(store.conn, task["task_id"])
        runner = TaskRunner(
            store, load_settings(make_env(tmp_path)), command_runner=fake_runner
        )

        async def scenario() -> None:
            await runner.start()
            await asyncio.sleep(0)
            await runner.stop()

        asyncio.run(scenario())
        loaded = get_task(store.conn, task["task_id"])
        assert loaded is not None
        assert loaded["status"] == "failed"
        assert "server restarted" in loaded["error"]
    finally:
        store.close()
