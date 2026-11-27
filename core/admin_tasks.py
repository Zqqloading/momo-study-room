"""管理后台长任务：持久化、状态、参数校验与日志。

只做任务表读写；不执行任何 CLI。执行器在 `bff/admin_task_runner.py`。
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

TASK_KINDS = ("ingest", "rebuild", "evaluate")
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled", "awaiting_review")

MAX_LOG_BYTES = 64 * 1024
LOG_TAIL_LINES = 20
LOG_TAIL_BYTES = 4 * 1024

EVAL_SUITES = ("probe", "asr", "questions", "scoring", "agent")

_REDACTIONS = (
    re.compile(
        r"(?i)([A-Z0-9_]{0,64}API_KEY\s*[=:]\s*)([^\s\"']+)"
    ),
    re.compile(
        r"(?i)(authorization\s*:\s*bearer\s+)([^\s\"']+)"
    ),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-]{12,})"),
)


class TaskParamError(ValueError):
    """任务参数不合法；`field` 给前端定位。"""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _canonical(params: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(params), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def redact_log(text: str) -> str:
    result = text
    for pattern in _REDACTIONS:
        result = pattern.sub(r"\1***", result)
    return result


def log_tail(text: str | None) -> list[str]:
    if not text:
        return []
    lines = text.splitlines()[-LOG_TAIL_LINES:]
    joined = "\n".join(lines)
    data = joined.encode("utf-8")
    if len(data) > LOG_TAIL_BYTES:
        joined = data[-LOG_TAIL_BYTES:].decode("utf-8", "ignore")
    return joined.splitlines()


def _bool(params: Mapping[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, default)
    if not isinstance(value, bool):
        raise TaskParamError(f"{key} 必须是布尔值", field=key)
    return value


def _relative_path(
    value: Any,
    *,
    field: str,
    prefixes: tuple[str, ...],
    suffix: tuple[str, ...] = (),
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskParamError(f"{field} 必须是非空字符串", field=field)
    text = value.strip().replace("\\", "/")
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise TaskParamError(f"{field} 必须是项目内相对路径", field=field)
    if not any(text.startswith(prefix) for prefix in prefixes):
        raise TaskParamError(
            f"{field} 必须在 {' / '.join(prefixes)} 下", field=field
        )
    if suffix and not text.endswith(suffix):
        raise TaskParamError(f"{field} 后缀必须是 {' / '.join(suffix)}", field=field)
    return text


def _reject_unknown(params: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise TaskParamError(f"未知参数：{', '.join(unknown)}", field=unknown[0])


def normalize_params(kind: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(params or {})
    if kind == "ingest":
        allowed = {
            "path",
            "dry_run",
            "emit_chunks",
            "extract",
            "confirm",
            "out",
        }
        _reject_unknown(raw, allowed)
        path = _relative_path(
            raw.get("path"),
            field="path",
            prefixes=("materials/",),
            suffix=(".md", ".html"),
        )
        confirm = _bool(raw, "confirm", False)
        if confirm:
            raise TaskParamError(
                "v1 不自动确认；confirm=true 需要非交互 --decisions，尚未启用",
                field="confirm",
            )
        out = raw.get("out")
        if out is not None:
            out = _relative_path(
                out, field="out", prefixes=("data/candidates/",)
            )
        return {
            "path": path,
            "dry_run": _bool(raw, "dry_run", False),
            "emit_chunks": _bool(raw, "emit_chunks", True),
            "extract": _bool(raw, "extract", False),
            "confirm": False,
            "out": out,
        }

    if kind == "rebuild":
        allowed = {"fts_only", "prune", "model", "dim"}
        _reject_unknown(raw, allowed)
        model = raw.get("model", "text-embedding-v4")
        if not isinstance(model, str) or not model.strip():
            raise TaskParamError("model 必须是非空字符串", field="model")
        dim = raw.get("dim", 1024)
        if isinstance(dim, bool) or not isinstance(dim, int) or not 1 <= dim <= 4096:
            raise TaskParamError("dim 必须是 1-4096 的整数", field="dim")
        return {
            "fts_only": _bool(raw, "fts_only", False),
            "prune": _bool(raw, "prune", False),
            "model": model.strip(),
            "dim": dim,
        }

    if kind == "evaluate":
        allowed = {"suites", "mode", "inputs", "out"}
        _reject_unknown(raw, allowed)
        suites_raw = raw.get("suites", list(EVAL_SUITES))
        if not isinstance(suites_raw, list) or not suites_raw:
            raise TaskParamError("suites 必须是非空数组", field="suites")
        suites: list[str] = []
        for item in suites_raw:
            if item not in EVAL_SUITES:
                raise TaskParamError(
                    f"不支持的 suite：{item}", field="suites"
                )
            if item not in suites:
                suites.append(item)
        mode = raw.get("mode", "auto")
        if mode not in ("auto", "real", "fake"):
            raise TaskParamError("mode 只能是 auto/real/fake", field="mode")
        inputs_raw = raw.get("inputs", {})
        if not isinstance(inputs_raw, dict):
            raise TaskParamError("inputs 必须是对象", field="inputs")
        inputs: dict[str, str] = {}
        for key, value in inputs_raw.items():
            if key not in ("questions", "labels", "answers"):
                raise TaskParamError(f"未知 input：{key}", field="inputs")
            inputs[key] = _relative_path(
                value,
                field=f"inputs.{key}",
                prefixes=("docs/designs/", "data/"),
            )
        out = raw.get("out", "data/admin-eval")
        out = _relative_path(
            out,
            field="out",
            prefixes=("data/admin-eval/", "data/admin-eval", "docs/designs/"),
        )
        return {
            "suites": suites,
            "mode": mode,
            "inputs": inputs,
            "out": out,
        }

    raise TaskParamError(f"未知任务类型：{kind}", field="kind")


def _payload(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "params": _load(row["params_json"], {}),
        "progress": _load(row["progress_json"], None),
        "log_tail": log_tail(row["log_text"]),
        "result": _load(row["result_json"], None),
        "error": row["error"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def create_task(
    conn: sqlite3.Connection,
    *,
    kind: str,
    params: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    """创建任务；重复返回已有任务。返回 (payload, created)。"""
    if kind not in TASK_KINDS:
        raise TaskParamError(f"未知任务类型：{kind}", field="kind")
    if params is not None and not isinstance(params, Mapping):
        raise TaskParamError("params 必须是对象", field="params")
    normalized = normalize_params(kind, params)
    params_json = _canonical(normalized)
    existing = conn.execute(
        """
        SELECT * FROM admin_tasks
        WHERE kind = ? AND params_json = ? AND status IN ('queued','running')
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (kind, params_json),
    ).fetchone()
    if existing is not None:
        return _payload(existing), False

    task_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO admin_tasks
          (id, kind, status, params_json, created_at)
        VALUES (?, ?, 'queued', ?, ?)
        """,
        (task_id, kind, params_json, _now()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM admin_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    return _payload(row), True


def get_task(conn: sqlite3.Connection, task_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM admin_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    return _payload(row) if row else None


def list_tasks(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    status: str | None = None,
    start: str | None = None,
    end: str | None = None,
    ids: str | None = None,
    page: int = 1,
    per_page: int = 25,
    sort: str | None = None,
    order: str | None = None,
) -> dict[str, Any]:
    sort_map = {
        "created_at": "created_at",
        "finished_at": "finished_at",
        "kind": "kind",
        "status": "status",
        "id": "id",
    }
    sort_key = sort or "created_at"
    if sort_key not in sort_map:
        raise TaskParamError(f"不支持的排序字段：{sort_key}", field="sort")
    direction = (order or "desc").lower()
    if direction not in ("asc", "desc"):
        raise TaskParamError("order 只能是 asc 或 desc", field="order")

    where: list[str] = []
    params: list[Any] = []
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if status:
        where.append("status = ?")
        params.append(status)
    if start:
        where.append("created_at >= ?")
        params.append(start)
    if end:
        where.append("created_at <= ?")
        params.append(end)
    if ids:
        values = [part.strip() for part in ids.split(",") if part.strip()]
        if len(values) > 100:
            raise TaskParamError("ids 最多 100 个", field="ids")
        marks = ",".join("?" for _ in values)
        where.append(f"id IN ({marks})")
        params.extend(values)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    page = max(1, int(page))
    per_page = min(max(1, int(per_page)), 100)
    total = conn.execute(
        f"SELECT COUNT(*) FROM admin_tasks {clause}", tuple(params)
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT * FROM admin_tasks {clause}
        ORDER BY {sort_map[sort_key]} {direction.upper()}, id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    return {"data": [_payload(row) for row in rows], "total": total}


def mark_running(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute(
        """
        UPDATE admin_tasks
        SET status = 'running', started_at = ?,
            progress_json = ?
        WHERE id = ? AND status = 'queued'
        """,
        (
            _now(),
            _json(
                {
                    "phase": "starting",
                    "current": None,
                    "total": None,
                    "message": "任务已启动",
                }
            ),
            task_id,
        ),
    )
    conn.commit()


def update_progress(
    conn: sqlite3.Connection, task_id: str, progress: Mapping[str, Any]
) -> None:
    conn.execute(
        "UPDATE admin_tasks SET progress_json = ? WHERE id = ?",
        (_json(dict(progress)), task_id),
    )
    conn.commit()


def append_log(conn: sqlite3.Connection, task_id: str, text: str) -> None:
    if not text:
        return
    row = conn.execute(
        "SELECT log_text FROM admin_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if row is None:
        return
    merged = redact_log((row["log_text"] or "") + text)
    data = merged.encode("utf-8")
    if len(data) > MAX_LOG_BYTES:
        merged = data[-MAX_LOG_BYTES:].decode("utf-8", "ignore")
    conn.execute(
        "UPDATE admin_tasks SET log_text = ? WHERE id = ?",
        (merged, task_id),
    )
    conn.commit()


def finish_task(
    conn: sqlite3.Connection,
    task_id: str,
    status: str,
    *,
    result: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"不是终态：{status}")
    conn.execute(
        """
        UPDATE admin_tasks
        SET status = ?, result_json = ?, error = ?, finished_at = ?
        WHERE id = ?
        """,
        (status, _json(dict(result) if result else None), error, _now(), task_id),
    )
    conn.commit()


def recover_tasks(conn: sqlite3.Connection) -> int:
    """服务重启：运行中的任务标失败；排队任务留给执行器重新入队。"""
    cursor = conn.execute(
        """
        UPDATE admin_tasks
        SET status = 'failed',
            error = 'server restarted before completion',
            finished_at = ?
        WHERE status = 'running'
        """,
        (_now(),),
    )
    conn.commit()
    return cursor.rowcount


def queued_task_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT id FROM admin_tasks
        WHERE status = 'queued'
        ORDER BY created_at ASC, id ASC
        """
    ).fetchall()
    return [str(row["id"]) for row in rows]
