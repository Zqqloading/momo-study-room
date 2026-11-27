"""管理后台长任务执行器：单 worker、子进程、日志、超时与恢复。

任务表读写由 `core.admin_tasks` 负责；这里只执行已验证的 CLI。
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from core.admin_tasks import (
    append_log,
    finish_task,
    get_task,
    mark_running,
    queued_task_ids,
    recover_tasks,
    update_progress,
)
from core.ingestion import material_id
from core.store import Store

from .config import Settings

CommandRunner = Callable[
    [Sequence[str], Callable[[str], None], float],
    Awaitable[tuple[int, list[str]]],
]


class TaskExecutionError(RuntimeError):
    """任务执行失败；消息会进 `admin_tasks.error`。"""


class TaskRunner:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        *,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._command_runner = command_runner or self._run_subprocess
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._current_process: asyncio.subprocess.Process | None = None
        self._stopping = False

    async def start(self) -> None:
        recover_tasks(self._store.conn)
        for task_id in queued_task_ids(self._store.conn):
            self._queue.put_nowait(task_id)
        self._worker = asyncio.create_task(self._run_worker())

    async def stop(self) -> None:
        self._stopping = True
        if self._current_process is not None:
            self._current_process.terminate()
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except (asyncio.CancelledError, Exception):
                pass
            self._worker = None

    async def submit(self, task_id: str) -> None:
        self._queue.put_nowait(task_id)

    async def _run_worker(self) -> None:
        while True:
            task_id = await self._queue.get()
            try:
                await self.execute(task_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - 兜底，防止 worker 退出
                finish_task(
                    self._store.conn,
                    task_id,
                    "failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            finally:
                self._queue.task_done()

    async def execute(self, task_id: str) -> None:
        task = get_task(self._store.conn, task_id)
        if task is None or task["status"] != "queued":
            return
        mark_running(self._store.conn, task_id)
        try:
            if task["kind"] == "ingest":
                status, result = await self._ingest(task)
            elif task["kind"] == "rebuild":
                status, result = await self._rebuild(task)
            elif task["kind"] == "evaluate":
                status, result = await self._evaluate(task)
            else:  # pragma: no cover - 表约束已挡住
                raise TaskExecutionError(f"未知任务类型：{task['kind']}")
        except TaskExecutionError as exc:
            finish_task(self._store.conn, task_id, "failed", error=str(exc))
            return
        except Exception as exc:
            finish_task(
                self._store.conn,
                task_id,
                "failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        finish_task(self._store.conn, task_id, status, result=result)

    # ---- 三类任务 ----

    async def _ingest(self, task: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        params = task["params"]
        db = str(self._settings.db_path)
        path = str(params["path"])
        mid = material_id(path)
        chunks = params.get("out") or f"data/candidates/{mid}.chunks.json"
        candidates = f"data/candidates/{mid}.candidates.json"
        run_ids: list[int] = []

        if params.get("dry_run"):
            run = await self._run_command(
                ["-m", "core.ingest", path, "--db", db, "--dry-run"],
                task["task_id"],
                "ingest",
                30 * 60,
            )
            run_ids.extend(run["pipeline_run_ids"])
            return "succeeded", {
                "dry_run": True,
                "path": path,
                "pipeline_run_ids": run_ids,
            }

        ingest_args = ["-m", "core.ingest", path, "--db", db]
        if params.get("emit_chunks"):
            ingest_args.extend(["--emit-chunks", "--out", chunks])
        ingest = await self._run_command(
            ingest_args, task["task_id"], "ingest", 30 * 60
        )
        run_ids.extend(ingest["pipeline_run_ids"])
        match = _search(
            ingest["lines"],
            r"material=(\S+)\s+v(\d+)\s+parent=(\d+)\s+child=(\d+)",
        )
        result: dict[str, Any] = {
            "path": path,
            "material_id": match.group(1) if match else mid,
            "version": int(match.group(2)) if match else None,
            "chunks_parent": int(match.group(3)) if match else None,
            "chunks_child": int(match.group(4)) if match else None,
            "chunks_path": chunks if params.get("emit_chunks") else None,
            "pipeline_run_ids": run_ids,
        }

        if not params.get("extract"):
            return "succeeded", result

        if not params.get("emit_chunks"):
            raise TaskExecutionError("extract=true 需要 emit_chunks=true")
        extract = await self._run_command(
            [
                "-m",
                "core.extract",
                chunks,
                "--db",
                db,
                "--out",
                candidates,
            ],
            task["task_id"],
            "extract",
            30 * 60,
        )
        run_ids.extend(extract["pipeline_run_ids"])
        extracted = _search(
            extract["lines"],
            r"candidates=(\d+)\s+warnings=(\d+)\s+failures=(\d+)",
        )
        result.update(
            {
                "candidates_path": candidates,
                "candidates": int(extracted.group(1)) if extracted else None,
                "warnings": int(extracted.group(2)) if extracted else None,
                "extract_failures": int(extracted.group(3)) if extracted else None,
                "pipeline_run_ids": run_ids,
            }
        )
        return "awaiting_review", result

    async def _rebuild(self, task: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        params = task["params"]
        db = str(self._settings.db_path)
        args = [
            "-m",
            "core.reindex",
            "--db",
            db,
            "--model",
            str(params["model"]),
            "--dim",
            str(params["dim"]),
        ]
        if params.get("fts_only"):
            args.append("--fts-only")
        if params.get("prune"):
            args.append("--prune")
        run = await self._run_command(
            args, task["task_id"], "reindex", 60 * 60
        )
        fts = _search(run["lines"], r"fts=(\d+)")
        embedded = _search(run["lines"], r"embedded=(\d+)")
        missing = _search(run["lines"], r"missing_before=(\d+)")
        pruned_embeddings = _search(run["lines"], r"pruned_embeddings=(\d+)")
        pruned_fts = _search(run["lines"], r"pruned_fts=(\d+)")
        return "succeeded", {
            "fts_rows": int(fts.group(1)) if fts else None,
            "embedded": int(embedded.group(1)) if embedded else None,
            "embeddings_added": int(embedded.group(1)) if embedded else None,
            "embeddings_pruned": (
                int(pruned_embeddings.group(1)) if pruned_embeddings else None
            ),
            "fts_pruned": int(pruned_fts.group(1)) if pruned_fts else None,
            "missing_before": int(missing.group(1)) if missing else None,
            "pipeline_run_ids": run["pipeline_run_ids"],
        }

    async def _evaluate(self, task: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        params = task["params"]
        out = Path(params["out"])
        out.mkdir(parents=True, exist_ok=True)
        items: list[dict[str, Any]] = []
        inputs = params.get("inputs") or {}
        mode = params.get("mode", "auto")
        for suite in params["suites"]:
            suite_dir = out / suite
            suite_dir.mkdir(parents=True, exist_ok=True)
            item = await self._run_suite(
                suite,
                mode=mode,
                inputs=inputs,
                out=out,
                suite_dir=suite_dir,
                task_id=task["task_id"],
            )
            items.append(item)
        executed = [item for item in items if item["status"] != "skipped"]
        failed = any(item["status"] == "failed" for item in items)
        passed = bool(executed) and all(item["passed"] for item in executed)
        return ("failed" if failed else "succeeded"), {
            "passed": passed,
            "items": items,
            "pipeline_run_ids": [],
        }

    async def _run_suite(
        self,
        suite: str,
        *,
        mode: str,
        inputs: Mapping[str, str],
        out: Path,
        suite_dir: Path,
        task_id: str,
    ) -> dict[str, Any]:
        if suite == "probe":
            args = [
                "-m",
                "bff.probe",
                "--mode",
                mode,
                "--out",
                str(suite_dir),
            ]
            return await self._suite_command(suite, args, task_id, suite_dir)

        if suite == "asr":
            args = ["-m", "bff.asr_eval", "--mode", mode]
            result = await self._suite_command(
                suite,
                args,
                task_id,
                suite_dir,
                allow_empty_audio=True,
                parse_report=True,
            )
            return result

        if suite == "questions":
            questions = inputs.get("questions")
            labels = inputs.get("labels")
            if not questions or not labels:
                return _skipped(suite, "缺少 inputs.questions / inputs.labels")
            out_dir = Path(questions).parent
            args = [
                "-m",
                "core.eval_questions",
                "--score",
                "--labels",
                labels,
                "--out",
                str(out_dir),
            ]
            return await self._suite_command(
                suite, args, task_id, out_dir, report="question-acceptance.md"
            )

        if suite == "scoring":
            answers = inputs.get("answers")
            if not answers:
                return _skipped(suite, "缺少 inputs.answers")
            args = [
                "-m",
                "core.eval_scoring",
                "--run",
                "--answers",
                answers,
                "--out",
                str(suite_dir),
            ]
            if mode != "auto":
                args.extend(["--mode", mode])
            return await self._suite_command(
                suite, args, task_id, suite_dir, report="scoring-acceptance.md"
            )

        if suite == "agent":
            if not getattr(self._settings, "agent_harness", False) or not getattr(
                self._settings, "agent_base_url", ""
            ):
                return _skipped(suite, "agent harness 未启用或未配置")
            args = ["-m", "bff.agent_smoke", "--out", str(suite_dir)]
            return await self._suite_command(
                suite,
                args,
                task_id,
                suite_dir,
                report="agent-harness-smoke.md",
            )

        return _skipped(suite, "未知 suite")

    async def _suite_command(
        self,
        suite: str,
        args: Sequence[str],
        task_id: str,
        report_dir: Path,
        *,
        report: str | None = None,
        allow_empty_audio: bool = False,
        parse_report: bool = False,
    ) -> dict[str, Any]:
        try:
            run = await self._run_command(args, task_id, f"evaluate:{suite}", 30 * 60)
        except TaskExecutionError as exc:
            text = str(exc)
            if allow_empty_audio and "还没有录音" in text:
                return _skipped(suite, "ASR 测试集没有录音")
            return {
                "name": suite,
                "status": "failed",
                "passed": False,
                "report": None,
                "reason": text,
            }
        report_path: str | None
        if parse_report:
            report_path = None
            for line in run["lines"]:
                if line.startswith("报告："):
                    report_path = line.split("：", 1)[1].strip()
                    break
        else:
            report_path = str(report_dir / report) if report else str(report_dir)
        return {
            "name": suite,
            "status": "succeeded",
            "passed": True,
            "report": report_path,
            "reason": None,
        }

    # ---- 命令执行 ----

    async def _run_command(
        self,
        args: Sequence[str],
        task_id: str,
        phase: str,
        timeout: float,
    ) -> dict[str, Any]:
        update_progress(
            self._store.conn,
            task_id,
            {
                "phase": phase,
                "current": None,
                "total": None,
                "message": f"执行 {phase}",
            },
        )
        lines: list[str] = []
        run_ids: list[int] = []

        def on_line(line: str) -> None:
            lines.append(line)
            match = re.match(r"pipeline_run_id=(\d+)", line)
            if match:
                run_ids.append(int(match.group(1)))
            append_log(self._store.conn, task_id, line + "\n")

        code, _ = await self._command_runner(args, on_line, timeout)
        if code != 0:
            tail = lines[-1] if lines else ""
            raise TaskExecutionError(
                f"{phase} 失败（exit {code}）" + (f"：{tail}" if tail else "")
            )
        return {"code": code, "lines": lines, "pipeline_run_ids": run_ids}

    async def _run_subprocess(
        self,
        args: Sequence[str],
        on_line: Callable[[str], None],
        timeout: float,
    ) -> tuple[int, list[str]]:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            *args,
            cwd=str(self._settings.project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        self._current_process = process
        lines: list[str] = []

        async def read_lines() -> None:
            assert process.stdout is not None
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    return
                line = raw.decode("utf-8", "replace").rstrip()
                lines.append(line)
                on_line(line)

        try:
            await asyncio.wait_for(read_lines(), timeout=timeout)
            code = await asyncio.wait_for(process.wait(), timeout=10)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise TaskExecutionError(f"任务超时（{int(timeout)}s）") from exc
        finally:
            self._current_process = None
        return code, lines


def _search(lines: Sequence[str], pattern: str) -> re.Match | None:
    for line in reversed(lines):
        match = re.search(pattern, line)
        if match:
            return match
    return None


def _skipped(suite: str, reason: str) -> dict[str, Any]:
    return {
        "name": suite,
        "status": "skipped",
        "passed": False,
        "report": None,
        "reason": reason,
    }
