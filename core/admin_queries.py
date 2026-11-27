"""管理后台只读查询：搜索、影响面、健康状态与修复计划。

所有函数只读：不写库、不调 provider。数据来自 SQLite 与已加载的 concepts.yaml。
v1 数据量很小（几十到几百行），跨表匹配在 Python 里做，避免过度 SQL。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .admin_repair import (
    repair_bank_question,
    repair_concept,
    repair_generated_question,
    repair_material,
    repair_session,
)
from .concepts import Concept
from .db import SCHEMA_VERSION
from .models import mastery_label

PROVENANCE_LABELS = {
    "chunk": "块级",
    "url": "URL 级",
    "concept": "仅概念级",
    "unmatched": "未匹配",
}
PROVENANCE_ORDER = ("chunk", "url", "concept", "unmatched")


def _dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _preview(text: Any, limit: int = 240) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _like(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


def _norm(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if text.startswith("local://"):
        text = text[len("local://") :]
    return text.casefold().lstrip("/")


def _material_keys(material: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    for raw in (material.get("source_url"), material.get("path")):
        norm = _norm(raw)
        if norm:
            keys.add(norm)
    return keys


def _source_matches(source_url: Any, keys: set[str]) -> bool:
    norm = _norm(source_url)
    return bool(norm) and norm in keys


def _provenance(level: str) -> dict[str, Any]:
    return {"level": level, "label": PROVENANCE_LABELS[level]}


def _concept_meta(
    concepts_by_id: Mapping[str, Concept], concept_id: str | None
) -> dict[str, Any]:
    if concept_id is None:
        return {"id": None, "name": None, "plain_def": None}
    concept = concepts_by_id.get(concept_id)
    if concept is None:
        return {"id": concept_id, "name": concept_id, "plain_def": ""}
    return {
        "id": concept.id,
        "name": concept.name,
        "plain_def": concept.plain_def,
    }


def _state_map(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {
        str(row["id"]): dict(row)
        for row in conn.execute("SELECT * FROM concepts")
    }


def _latest_assessment(
    conn: sqlite3.Connection, concept_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT q.session_id AS session_id,
               COALESCE(s.date, a.date) AS date,
               AVG(q.score) AS avg_score,
               MIN(q.score) AS min_score,
               COUNT(*) AS scored
        FROM session_questions q
        LEFT JOIN sessions s ON s.id = q.session_id
        LEFT JOIN agent_sessions a ON a.session_id = q.session_id
        WHERE q.concept_id = ? AND q.score IS NOT NULL
        GROUP BY q.session_id
        ORDER BY date DESC, q.session_id DESC
        LIMIT 1
        """,
        (concept_id,),
    ).fetchone()
    return dict(row) if row else None


def _session_rows(
    conn: sqlite3.Connection, session_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    if not session_ids:
        return {}
    placeholders = ",".join("?" for _ in session_ids)
    rows = conn.execute(
        f"""
        SELECT a.session_id, a.date, a.kind, a.status AS agent_status,
               a.concept_id, s.status AS final_status, s.session_score,
               s.input_mode, s.minutes
        FROM agent_sessions a
        LEFT JOIN sessions s ON s.id = a.session_id
        WHERE a.session_id IN ({placeholders})
        """,
        tuple(session_ids),
    )
    found = {str(row["session_id"]): dict(row) for row in rows}
    missing = [sid for sid in session_ids if sid not in found]
    if missing:
        marks = ",".join("?" for _ in missing)
        rows = conn.execute(
            f"""
            SELECT id AS session_id, date, kind, 'finished' AS agent_status,
                   concept_id, status AS final_status, session_score,
                   input_mode, minutes
            FROM sessions WHERE id IN ({marks})
            """,
            tuple(missing),
        )
        found.update({str(row["session_id"]): dict(row) for row in rows})
    return found


def _material_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return _dicts(
        conn.execute(
            """
            SELECT id, title, path, format, version, status, source_url,
                   added_at, content_hash
            FROM materials ORDER BY title
            """
        )
    )


def _material_by_key(
    materials: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    by_key: dict[str, Mapping[str, Any]] = {}
    for material in materials:
        for key in _material_keys(material):
            by_key.setdefault(key, material)
    return by_key


def _match_material(
    source_url: Any, by_key: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    norm = _norm(source_url)
    return by_key.get(norm) if norm else None


# ---------------------------------------------------------------------------
# 搜索
# ---------------------------------------------------------------------------

def search(
    conn: sqlite3.Connection,
    concepts: Sequence[Concept],
    query: str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    needle = query.strip()
    if not needle:
        return {
            "query": "",
            "groups": {
                "materials": [],
                "concepts": [],
                "questions": [],
                "sessions": [],
            },
            "counts": {
                "materials": 0,
                "concepts": 0,
                "questions": 0,
                "sessions": 0,
            },
        }

    like = _like(needle)
    states = _state_map(conn)
    concepts_by_id = {concept.id: concept for concept in concepts}

    materials = _dicts(
        conn.execute(
            """
            SELECT id, title, path, version, status, source_url
            FROM materials
            WHERE title LIKE ? ESCAPE '\\'
               OR path LIKE ? ESCAPE '\\'
               OR source_url LIKE ? ESCAPE '\\'
            ORDER BY title
            LIMIT ?
            """,
            (like, like, like, limit),
        )
    )
    material_items = [
        {
            "type": "material",
            "id": row["id"],
            "title": row["title"],
            "subtitle": f"{row['path']} · v{row['version']} · {row['status']}",
            "meta": row.get("source_url") or "",
        }
        for row in materials
    ]

    concept_items: list[dict[str, Any]] = []
    folded = needle.casefold()
    seen: set[str] = set()
    for concept in concepts:
        haystack = " ".join(
            [concept.id, concept.name, *concept.aliases, concept.plain_def]
        ).casefold()
        if folded not in haystack:
            continue
        state = states.get(concept.id, {})
        concept_items.append(
            {
                "type": "concept",
                "id": concept.id,
                "title": concept.name,
                "subtitle": (
                    f"掌握度 {state.get('mastery', 0)}"
                    f" · {state.get('status', 'proposed')}"
                ),
                "meta": _preview(concept.plain_def, 120),
            }
        )
        seen.add(concept.id)
    for concept_id, state in states.items():
        if concept_id in seen or concept_id in concepts_by_id:
            continue
        if folded not in concept_id.casefold():
            continue
        concept_items.append(
            {
                "type": "concept",
                "id": concept_id,
                "title": concept_id,
                "subtitle": (
                    f"掌握度 {state.get('mastery', 0)}"
                    f" · {state.get('status', 'orphaned')}"
                ),
                "meta": "concepts.yaml 里没有这个 id",
            }
        )
    concept_items = concept_items[:limit]

    bank_rows = _dicts(
        conn.execute(
            """
            SELECT id, concept_id, kind, question_text, source_url,
                   source_excerpt
            FROM question_bank
            WHERE id LIKE ? ESCAPE '\\'
               OR concept_id LIKE ? ESCAPE '\\'
               OR question_text LIKE ? ESCAPE '\\'
               OR source_excerpt LIKE ? ESCAPE '\\'
            ORDER BY id
            LIMIT ?
            """,
            (like, like, like, like, limit),
        )
    )
    session_rows = _dicts(
        conn.execute(
            """
            SELECT id, session_id, concept_id, question_text, answer_text,
                   feedback, score, question_bank_id, source_chunk_id
            FROM session_questions
            WHERE question_text LIKE ? ESCAPE '\\'
               OR answer_text LIKE ? ESCAPE '\\'
               OR feedback LIKE ? ESCAPE '\\'
            ORDER BY id DESC
            LIMIT ?
            """,
            (like, like, like, limit),
        )
    )
    question_items: list[dict[str, Any]] = []
    for row in bank_rows:
        question_items.append(
            {
                "type": "bank_question",
                "id": row["id"],
                "title": _preview(row["question_text"], 90),
                "subtitle": f"题库 · {row['concept_id']} · {row['kind']}",
                "meta": row.get("source_url") or "",
            }
        )
    for row in session_rows:
        question_items.append(
            {
                "type": "session_question",
                "id": str(row["id"]),
                "title": _preview(row["question_text"], 90),
                "subtitle": (
                    f"会话题 · {row['session_id']}"
                    f" · {row['score'] if row['score'] is not None else '未评分'}"
                ),
                "meta": row.get("concept_id") or "",
            }
        )
    question_items = question_items[:limit]

    coach_rows = _dicts(
        conn.execute(
            """
            SELECT a.session_id, a.date, a.kind, a.status AS agent_status,
                   a.concept_id, s.status AS final_status, s.session_score
            FROM agent_sessions a
            LEFT JOIN sessions s ON s.id = a.session_id
            WHERE a.session_id LIKE ? ESCAPE '\\'
               OR a.concept_id LIKE ? ESCAPE '\\'
               OR a.date LIKE ? ESCAPE '\\'
               OR s.asr_text LIKE ? ESCAPE '\\'
               OR s.explained_text LIKE ? ESCAPE '\\'
               OR EXISTS (
                 SELECT 1 FROM session_notes n
                 WHERE n.session_id = a.session_id
                   AND (
                     n.input_text LIKE ? ESCAPE '\\'
                     OR n.output_text LIKE ? ESCAPE '\\'
                   )
               )
            ORDER BY a.date DESC, a.started_at DESC
            LIMIT ?
            """,
            (like, like, like, like, like, like, like, limit),
        )
    )
    conversation_rows = _dicts(
        conn.execute(
            """
            SELECT c.id, c.title, c.updated_at
            FROM conversations c
            WHERE c.title LIKE ? ESCAPE '\\'
               OR EXISTS (
                 SELECT 1 FROM conversation_messages m
                 WHERE m.conversation_id = c.id
                   AND m.text LIKE ? ESCAPE '\\'
               )
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (like, like, limit),
        )
    )
    session_items: list[dict[str, Any]] = []
    for row in coach_rows:
        session_items.append(
            {
                "type": "session",
                "id": row["session_id"],
                "title": f"学习会话 · {row['date']}",
                "subtitle": (
                    f"{row['agent_status']}"
                    f" · {row['final_status'] or '未结算'}"
                ),
                "meta": row.get("concept_id") or "",
            }
        )
    for row in conversation_rows:
        session_items.append(
            {
                "type": "conversation",
                "id": row["id"],
                "title": row["title"] or "未命名对话",
                "subtitle": f"自由对话 · {row['updated_at']}",
                "meta": "",
            }
        )
    session_items = session_items[:limit]

    return {
        "query": needle,
        "groups": {
            "materials": material_items,
            "concepts": concept_items,
            "questions": question_items,
            "sessions": session_items,
        },
        "counts": {
            "materials": len(material_items),
            "concepts": len(concept_items),
            "questions": len(question_items),
            "sessions": len(session_items),
        },
    }


class AdminListError(ValueError):
    """列表参数非法；路由返回 400。"""


def _page_args(page: int, per_page: int) -> tuple[int, int]:
    page = max(1, int(page))
    per_page = min(max(1, int(per_page)), 100)
    return page, per_page


def _ids(value: str | None, *, integer: bool = False) -> list[Any] | None:
    if not value:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) > 100:
        raise AdminListError("ids 最多 100 个")
    if not integer:
        return parts
    try:
        return [int(part) for part in parts]
    except ValueError as exc:
        raise AdminListError("ids 必须是整数") from exc


def _sort_sql(
    sort: str | None,
    order: str | None,
    allowed: Mapping[str, str],
    *,
    default_sort: str,
    default_order: str = "asc",
) -> tuple[str, str]:
    key = sort or default_sort
    if key not in allowed:
        raise AdminListError(f"不支持的排序字段：{key}")
    direction = (order or default_order).lower()
    if direction not in ("asc", "desc"):
        raise AdminListError("order 只能是 asc 或 desc")
    return allowed[key], direction.upper()


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------

def list_materials(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    status: str | None = None,
    format: str | None = None,
    ids: str | None = None,
    page: int = 1,
    per_page: int = 25,
    sort: str | None = None,
    order: str | None = None,
) -> dict[str, Any]:
    if status and status not in ("active", "missing"):
        raise AdminListError("status 只能是 active/missing")
    if format and format not in ("md", "html"):
        raise AdminListError("format 只能是 md/html")
    column, direction = _sort_sql(
        sort,
        order,
        {
            "title": "title",
            "path": "path",
            "version": "version",
            "added_at": "added_at",
            "status": "status",
        },
        default_sort="title",
    )
    where: list[str] = []
    params: list[Any] = []
    if q:
        like = _like(q)
        where.append(
            "(title LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\' "
            "OR source_url LIKE ? ESCAPE '\\')"
        )
        params.extend([like, like, like])
    if status:
        where.append("status = ?")
        params.append(status)
    if format:
        where.append("format = ?")
        params.append(format)
    ids_list = _ids(ids)
    if ids_list:
        marks = ",".join("?" for _ in ids_list)
        where.append(f"id IN ({marks})")
        params.extend(ids_list)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    page, per_page = _page_args(page, per_page)
    total = conn.execute(
        f"SELECT COUNT(*) FROM materials {clause}", tuple(params)
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT id, title, path, format, version, status, source_url, added_at
        FROM materials {clause}
        ORDER BY {column} {direction}, id
        LIMIT ? OFFSET ?
        """,
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    return {"data": _dicts(rows), "total": total}


def list_concepts(
    conn: sqlite3.Connection,
    concepts: Sequence[Concept],
    *,
    q: str | None = None,
    status: str | None = None,
    mastery: int | None = None,
    ids: str | None = None,
    page: int = 1,
    per_page: int = 25,
    sort: str | None = None,
    order: str | None = None,
) -> dict[str, Any]:
    allowed_status = {"proposed", "active", "known", "skipped", "orphaned"}
    if status and status not in allowed_status:
        raise AdminListError("status 不合法")
    if mastery is not None and not 0 <= mastery <= 5:
        raise AdminListError("mastery 必须是 0-5")
    sort_key = sort or "mastery"
    if sort_key not in ("id", "name", "mastery", "status", "review_due_at"):
        raise AdminListError(f"不支持的排序字段：{sort_key}")
    direction = (order or "asc").lower()
    if direction not in ("asc", "desc"):
        raise AdminListError("order 只能是 asc 或 desc")

    states = _state_map(conn)
    concepts_by_id = {concept.id: concept for concept in concepts}
    ids_set = set(_ids(ids) or [])
    folded = (q or "").casefold()
    items: list[dict[str, Any]] = []

    for concept_id, state in states.items():
        concept = concepts_by_id.get(concept_id)
        haystack = " ".join(
            [
                concept_id,
                concept.name if concept else "",
                *(concept.aliases if concept else ()),
                concept.plain_def if concept else "",
            ]
        ).casefold()
        if folded and folded not in haystack:
            continue
        if status and state["status"] != status:
            continue
        if mastery is not None and int(state["mastery"]) != mastery:
            continue
        if ids_set and concept_id not in ids_set:
            continue
        items.append(
            {
                "id": concept_id,
                "name": concept.name if concept else concept_id,
                "plain_def": concept.plain_def if concept else "",
                "aliases": list(concept.aliases) if concept else [],
                "difficulty": concept.difficulty if concept else None,
                "prerequisites": list(concept.prerequisites) if concept else [],
                "mastery": state["mastery"],
                "mastery_label": mastery_label(int(state["mastery"])),
                "status": state["status"],
                "last_seen": state.get("last_seen"),
                "review_due_at": state.get("review_due_at"),
                "source_url": concept.source.url if concept else None,
                "source_material": concept.source.material if concept else None,
            }
        )

    for concept in concepts:
        if concept.id in states:
            continue
        haystack = " ".join(
            [concept.id, concept.name, *concept.aliases, concept.plain_def]
        ).casefold()
        if folded and folded not in haystack:
            continue
        if status and status != "proposed":
            continue
        if mastery is not None and mastery != 0:
            continue
        if ids_set and concept.id not in ids_set:
            continue
        items.append(
            {
                "id": concept.id,
                "name": concept.name,
                "plain_def": concept.plain_def,
                "aliases": list(concept.aliases),
                "difficulty": concept.difficulty,
                "prerequisites": list(concept.prerequisites),
                "mastery": 0,
                "mastery_label": mastery_label(0),
                "status": "proposed",
                "last_seen": None,
                "review_due_at": None,
                "source_url": concept.source.url,
                "source_material": concept.source.material,
            }
        )

    def key(item: dict[str, Any]) -> Any:
        if sort_key == "name":
            return (str(item["name"]).casefold(), item["id"])
        if sort_key == "review_due_at":
            return (item["review_due_at"] or "9999-12-31", item["id"])
        return (item[sort_key], item["id"])

    items.sort(key=key, reverse=direction == "desc")
    page, per_page = _page_args(page, per_page)
    start = (page - 1) * per_page
    return {"data": items[start : start + per_page], "total": len(items)}


def list_bank_questions(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    concept_id: str | None = None,
    kind: str | None = None,
    ids: str | None = None,
    page: int = 1,
    per_page: int = 25,
    sort: str | None = None,
    order: str | None = None,
) -> dict[str, Any]:
    if kind and kind not in ("recall", "discriminate", "apply"):
        raise AdminListError("kind 只能是 recall/discriminate/apply")
    column, direction = _sort_sql(
        sort,
        order,
        {"id": "id", "concept_id": "concept_id", "kind": "kind"},
        default_sort="id",
    )
    where: list[str] = []
    params: list[Any] = []
    if q:
        like = _like(q)
        where.append(
            "(id LIKE ? ESCAPE '\\' OR concept_id LIKE ? ESCAPE '\\' "
            "OR question_text LIKE ? ESCAPE '\\' "
            "OR source_excerpt LIKE ? ESCAPE '\\')"
        )
        params.extend([like, like, like, like])
    if concept_id:
        where.append("concept_id = ?")
        params.append(concept_id)
    if kind:
        where.append("kind = ?")
        params.append(kind)
    ids_list = _ids(ids)
    if ids_list:
        marks = ",".join("?" for _ in ids_list)
        where.append(f"id IN ({marks})")
        params.extend(ids_list)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    page, per_page = _page_args(page, per_page)
    total = conn.execute(
        f"SELECT COUNT(*) FROM question_bank {clause}", tuple(params)
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT id, concept_id, kind, question_text, source_url, source_excerpt
        FROM question_bank {clause}
        ORDER BY {column} {direction}
        LIMIT ? OFFSET ?
        """,
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    return {"data": _dicts(rows), "total": total}


def list_session_questions(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    session_id: str | None = None,
    concept_id: str | None = None,
    question_bank_id: str | None = None,
    min_score: int | None = None,
    max_score: int | None = None,
    ids: str | None = None,
    page: int = 1,
    per_page: int = 25,
    sort: str | None = None,
    order: str | None = None,
) -> dict[str, Any]:
    for name, value in (("min_score", min_score), ("max_score", max_score)):
        if value is not None and not 0 <= value <= 100:
            raise AdminListError(f"{name} 必须是 0-100")
    column, direction = _sort_sql(
        sort,
        order,
        {"id": "id", "score": "score", "created_at": "created_at"},
        default_sort="id",
        default_order="desc",
    )
    where: list[str] = []
    params: list[Any] = []
    if q:
        like = _like(q)
        where.append(
            "(question_text LIKE ? ESCAPE '\\' "
            "OR answer_text LIKE ? ESCAPE '\\' "
            "OR feedback LIKE ? ESCAPE '\\')"
        )
        params.extend([like, like, like])
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    if concept_id:
        where.append("concept_id = ?")
        params.append(concept_id)
    if question_bank_id:
        where.append("question_bank_id = ?")
        params.append(question_bank_id)
    if min_score is not None:
        where.append("score >= ?")
        params.append(min_score)
    if max_score is not None:
        where.append("score <= ?")
        params.append(max_score)
    ids_list = _ids(ids, integer=True)
    if ids_list:
        marks = ",".join("?" for _ in ids_list)
        where.append(f"id IN ({marks})")
        params.extend(ids_list)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    page, per_page = _page_args(page, per_page)
    total = conn.execute(
        f"SELECT COUNT(*) FROM session_questions {clause}", tuple(params)
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT id, session_id, concept_id, question_bank_id, question_role,
               kind, question_type, question_text, score, source_url,
               source_chunk_id, created_at
        FROM session_questions {clause}
        ORDER BY {column} {direction}
        LIMIT ? OFFSET ?
        """,
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    return {"data": _dicts(rows), "total": total}


def list_sessions(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    concept_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    ids: str | None = None,
    page: int = 1,
    per_page: int = 25,
    sort: str | None = None,
    order: str | None = None,
) -> dict[str, Any]:
    if status and status not in (
        "active",
        "finished",
        "abandoned",
        "completed",
        "partial",
        "unscored",
    ):
        raise AdminListError("status 不合法")
    if kind and kind not in ("daily", "review"):
        raise AdminListError("kind 只能是 daily/review")
    column, direction = _sort_sql(
        sort,
        order,
        {
            "date": "a.date",
            "session_score": "s.session_score",
            "session_id": "a.session_id",
        },
        default_sort="date",
        default_order="desc",
    )
    where: list[str] = []
    params: list[Any] = []
    if q:
        like = _like(q)
        where.append(
            "(a.session_id LIKE ? ESCAPE '\\' "
            "OR a.concept_id LIKE ? ESCAPE '\\' "
            "OR a.date LIKE ? ESCAPE '\\' "
            "OR s.asr_text LIKE ? ESCAPE '\\' "
            "OR s.explained_text LIKE ? ESCAPE '\\' "
            "OR EXISTS (SELECT 1 FROM session_notes n WHERE n.session_id = a.session_id "
            "AND (n.input_text LIKE ? ESCAPE '\\' OR n.output_text LIKE ? ESCAPE '\\')))"
        )
        params.extend([like] * 7)
    if status:
        where.append("(a.status = ? OR s.status = ?)")
        params.extend([status, status])
    if kind:
        where.append("a.kind = ?")
        params.append(kind)
    if concept_id:
        where.append("a.concept_id = ?")
        params.append(concept_id)
    if start:
        where.append("a.date >= ?")
        params.append(start)
    if end:
        where.append("a.date <= ?")
        params.append(end)
    ids_list = _ids(ids)
    if ids_list:
        marks = ",".join("?" for _ in ids_list)
        where.append(f"a.session_id IN ({marks})")
        params.extend(ids_list)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    page, per_page = _page_args(page, per_page)
    total = conn.execute(
        f"""
        SELECT COUNT(*) FROM agent_sessions a
        LEFT JOIN sessions s ON s.id = a.session_id
        {clause}
        """,
        tuple(params),
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT a.session_id, a.date, a.kind, a.status AS agent_status,
               a.concept_id, a.input_mode, s.status AS final_status,
               s.session_score, s.minutes,
               (SELECT COUNT(*) FROM session_questions q
                WHERE q.session_id = a.session_id) AS question_count
        FROM agent_sessions a
        LEFT JOIN sessions s ON s.id = a.session_id
        {clause}
        ORDER BY {column} {direction}, a.session_id
        LIMIT ? OFFSET ?
        """,
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    return {"data": _dicts(rows), "total": total}


def list_conversations(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    start: str | None = None,
    end: str | None = None,
    ids: str | None = None,
    page: int = 1,
    per_page: int = 25,
    sort: str | None = None,
    order: str | None = None,
) -> dict[str, Any]:
    column, direction = _sort_sql(
        sort,
        order,
        {
            "updated_at": "c.updated_at",
            "created_at": "c.created_at",
            "title": "c.title",
        },
        default_sort="updated_at",
        default_order="desc",
    )
    where: list[str] = []
    params: list[Any] = []
    if q:
        like = _like(q)
        where.append(
            "(c.title LIKE ? ESCAPE '\\' OR EXISTS ("
            "SELECT 1 FROM conversation_messages m "
            "WHERE m.conversation_id = c.id AND m.text LIKE ? ESCAPE '\\'))"
        )
        params.extend([like, like])
    if start:
        where.append("c.updated_at >= ?")
        params.append(start)
    if end:
        where.append("c.updated_at <= ?")
        params.append(end)
    ids_list = _ids(ids)
    if ids_list:
        marks = ",".join("?" for _ in ids_list)
        where.append(f"c.id IN ({marks})")
        params.extend(ids_list)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    page, per_page = _page_args(page, per_page)
    total = conn.execute(
        f"SELECT COUNT(*) FROM conversations c {clause}", tuple(params)
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT c.id, c.title, c.created_at, c.updated_at,
               (SELECT COUNT(*) FROM conversation_messages m
                WHERE m.conversation_id = c.id) AS message_count
        FROM conversations c {clause}
        ORDER BY {column} {direction}, c.id
        LIMIT ? OFFSET ?
        """,
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    return {"data": _dicts(rows), "total": total}


def list_pipeline_runs(
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
    if kind and kind not in ("ingest", "extract", "confirm", "reindex"):
        raise AdminListError("kind 不合法")
    if status and status not in ("running", "succeeded", "failed", "partial"):
        raise AdminListError("status 不合法")
    column, direction = _sort_sql(
        sort,
        order,
        {"id": "id", "started_at": "started_at", "kind": "kind"},
        default_sort="id",
        default_order="desc",
    )
    where: list[str] = []
    params: list[Any] = []
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if status:
        where.append("status = ?")
        params.append(status)
    if start:
        where.append("started_at >= ?")
        params.append(start)
    if end:
        where.append("started_at <= ?")
        params.append(end)
    ids_list = _ids(ids, integer=True)
    if ids_list:
        marks = ",".join("?" for _ in ids_list)
        where.append(f"id IN ({marks})")
        params.extend(ids_list)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    page, per_page = _page_args(page, per_page)
    total = conn.execute(
        f"SELECT COUNT(*) FROM pipeline_runs {clause}", tuple(params)
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT id, kind, started_at, finished_at, status, input, stats_json, error
        FROM pipeline_runs {clause}
        ORDER BY {column} {direction}
        LIMIT ? OFFSET ?
        """,
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    data = []
    for row in rows:
        item = dict(row)
        item["stats"] = _json(item.pop("stats_json", None))
        data.append(item)
    return {"data": data, "total": total}


def pipeline_run_detail(
    conn: sqlite3.Connection, run_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, kind, started_at, finished_at, status, input, stats_json, error
        FROM pipeline_runs WHERE id = ?
        """,
        (int(run_id),),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["stats"] = _json(item.pop("stats_json", None))
    return item


MATERIAL_SUFFIXES = {".md", ".html"}


def scan_materials(
    conn: sqlite3.Connection, content_dir: str | Path
) -> dict[str, Any]:
    """扫描 materials/ 下的文件，与 DB 中的材料比较。只读，不写库。"""
    content_root = Path(content_dir).resolve()
    root = content_root / "materials"
    rows = _dicts(
        conn.execute(
            "SELECT id, title, path, version, content_hash, status FROM materials"
        )
    )
    by_path = {_norm(row["path"]): row for row in rows}
    new: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    unchanged = 0

    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in MATERIAL_SUFFIXES:
                continue
            try:
                rel = path.relative_to(content_root).as_posix()
                data = path.read_bytes()
            except OSError as exc:
                errors.append({"path": path.as_posix(), "error": str(exc)})
                continue
            norm = _norm(rel)
            seen.add(norm)
            digest = hashlib.sha256(data).hexdigest()
            item = {
                "path": rel,
                "name": path.name,
                "size": len(data),
                "modified_at": datetime.fromtimestamp(
                    path.stat().st_mtime
                ).astimezone().isoformat(timespec="seconds"),
            }
            db = by_path.get(norm)
            if db is None:
                new.append(item)
            elif db["content_hash"] != digest:
                changed.append(
                    {
                        **item,
                        "material_id": db["id"],
                        "db_version": db["version"],
                    }
                )
            else:
                unchanged += 1

    missing = [
        {
            "id": row["id"],
            "title": row["title"],
            "path": row["path"],
            "version": row["version"],
            "status": row["status"],
        }
        for row in rows
        if _norm(row["path"]) not in seen
    ]
    return {
        "root": "materials",
        "new": new,
        "changed": changed,
        "unchanged": unchanged,
        "missing": missing,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# 材料详情
# ---------------------------------------------------------------------------

def material_detail(
    conn: sqlite3.Connection,
    concepts: Sequence[Concept],
    material_id: str,
    *,
    history: bool = False,
    db_path: str | Path,
    content_dir: str | Path,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM materials WHERE id = ?", (material_id,)
    ).fetchone()
    if row is None:
        return None
    material = dict(row)
    current_version = int(material["version"])
    keys = _material_keys(material)
    concepts_by_id = {concept.id: concept for concept in concepts}
    states = _state_map(conn)

    version_rows = _dicts(
        conn.execute(
            """
            SELECT material_version AS version,
                   SUM(level = 'parent') AS parents,
                   SUM(level = 'child') AS children,
                   COUNT(*) AS total
            FROM material_chunks
            WHERE material_id = ?
            GROUP BY material_version
            ORDER BY material_version DESC
            """,
            (material_id,),
        )
    )
    for item in version_rows:
        item["current"] = int(item["version"]) == current_version

    chunks = _dicts(
        conn.execute(
            """
            SELECT id, material_version AS version, level, heading_path,
                   ordinal, token_count, substr(text, 1, 240) AS preview
            FROM material_chunks
            WHERE material_id = ?
            ORDER BY material_version DESC, ordinal
            """,
            (material_id,),
        )
    )
    if not history:
        chunks = [item for item in chunks if int(item["version"]) == current_version]

    source_rows = _dicts(
        conn.execute(
            """
            SELECT cs.concept_id, cs.chunk_id, cs.excerpt, cs.is_primary,
                   mc.material_version AS version, mc.heading_path, mc.level
            FROM concept_sources cs
            JOIN material_chunks mc ON mc.id = cs.chunk_id
            WHERE mc.material_id = ?
            ORDER BY cs.concept_id, mc.material_version DESC
            """,
            (material_id,),
        )
    )
    if not history:
        source_rows = [
            item for item in source_rows if int(item["version"]) == current_version
        ]

    concept_items: dict[str, dict[str, Any]] = {}
    for item in source_rows:
        concept_id = str(item["concept_id"])
        meta = _concept_meta(concepts_by_id, concept_id)
        state = states.get(concept_id, {})
        entry = concept_items.setdefault(
            concept_id,
            {
                "id": concept_id,
                "name": meta["name"],
                "plain_def": meta["plain_def"],
                "mastery": state.get("mastery", 0),
                "mastery_label": mastery_label(int(state.get("mastery", 0))),
                "status": state.get("status", "proposed"),
                "versions": [],
                "chunk_id": item["chunk_id"],
                "heading_path": item.get("heading_path"),
                "excerpt": item.get("excerpt"),
                "is_primary": bool(item.get("is_primary")),
            },
        )
        version = int(item["version"])
        if version not in entry["versions"]:
            entry["versions"].append(version)
        if version == current_version:
            entry["chunk_id"] = item["chunk_id"]
            entry["heading_path"] = item.get("heading_path")
            entry["excerpt"] = item.get("excerpt")
            entry["is_primary"] = bool(item.get("is_primary"))
    concept_list = sorted(
        concept_items.values(), key=lambda item: item["name"] or item["id"]
    )
    concept_ids = set(concept_items)

    bank_rows = _dicts(conn.execute("SELECT * FROM question_bank ORDER BY id"))
    bank_matches: dict[str, dict[str, Any]] = {}
    for item in bank_rows:
        source_match = _source_matches(item.get("source_url"), keys)
        concept_match = str(item.get("concept_id")) in concept_ids
        if not source_match and not concept_match:
            continue
        level = "url" if source_match else "concept"
        bank_matches[str(item["id"])] = {
            "id": item["id"],
            "concept_id": item["concept_id"],
            "kind": item["kind"],
            "question_text": item["question_text"],
            "source_url": item["source_url"],
            "source_excerpt": item["source_excerpt"],
            "provenance": _provenance(level),
        }
    bank_ids = set(bank_matches)

    question_rows = _dicts(
        conn.execute(
            """
            SELECT q.*, mc.material_id AS chunk_material_id,
                   mc.material_version AS chunk_material_version,
                   mc.heading_path AS chunk_heading_path
            FROM session_questions q
            LEFT JOIN material_chunks mc ON mc.id = q.source_chunk_id
            ORDER BY q.id DESC
            """
        )
    )
    question_matches: dict[int, dict[str, Any]] = {}
    for item in question_rows:
        chunk_match = item.get("chunk_material_id") == material_id
        chunk_version = (
            int(item["chunk_material_version"])
            if item.get("chunk_material_version") is not None
            else None
        )
        if chunk_match and not history and chunk_version != current_version:
            continue
        source_match = _source_matches(item.get("source_url"), keys)
        bank = bank_matches.get(str(item.get("question_bank_id") or ""))
        concept_match = str(item.get("concept_id")) in concept_ids
        if chunk_match:
            level = "chunk"
        elif source_match:
            level = "url"
        elif bank is not None and bank["provenance"]["level"] == "url":
            level = "url"
        elif bank is not None or concept_match:
            level = "concept"
        else:
            continue
        question_matches[int(item["id"])] = {
            "id": int(item["id"]),
            "session_id": item["session_id"],
            "concept_id": item.get("concept_id"),
            "question_text": item["question_text"],
            "question_type": item.get("question_type"),
            "score": item.get("score"),
            "answer_text": _preview(item.get("answer_text"), 240),
            "question_bank_id": item.get("question_bank_id"),
            "source_chunk_id": item.get("source_chunk_id"),
            "material_version": chunk_version if chunk_match else None,
            "provenance": _provenance(level),
        }

    session_ids = sorted({item["session_id"] for item in question_matches.values()})
    sessions = _session_rows(conn, session_ids)
    question_counts = Counter(
        item["session_id"] for item in question_matches.values()
    )
    session_items = []
    for session_id in session_ids:
        session = sessions.get(session_id)
        if session is None:
            session_items.append(
                {
                    "session_id": session_id,
                    "date": None,
                    "kind": None,
                    "agent_status": "unknown",
                    "final_status": None,
                    "session_score": None,
                    "question_count": question_counts[session_id],
                }
            )
            continue
        session_items.append(
            {
                **session,
                "question_count": question_counts[session_id],
            }
        )

    citations: dict[int, dict[str, Any]] = {}
    for message in conn.execute(
        """
        SELECT m.id, m.conversation_id, m.role, m.text, m.sources_json,
               m.created_at, c.title
        FROM conversation_messages m
        LEFT JOIN conversations c ON c.id = m.conversation_id
        WHERE m.sources_json IS NOT NULL
        ORDER BY m.id DESC
        """
    ):
        sources = _json(message["sources_json"])
        if not isinstance(sources, list):
            continue
        matched = [
            source
            for source in sources
            if isinstance(source, dict)
            and _source_matches(source.get("url"), keys)
        ]
        if not matched:
            continue
        citations[int(message["id"])] = {
            "message_id": int(message["id"]),
            "conversation_id": message["conversation_id"],
            "conversation_title": message["title"] or "未命名对话",
            "role": message["role"],
            "excerpt": _preview(message["text"], 200),
            "sources": matched,
            "created_at": message["created_at"],
            "provenance": _provenance("url"),
        }

    provenance = Counter(
        item["provenance"]["level"]
        for item in [*bank_matches.values(), *question_matches.values()]
    )
    counts = {
        "versions": len(version_rows),
        "chunks": len(chunks),
        "parents": sum(1 for item in chunks if item["level"] == "parent"),
        "children": sum(1 for item in chunks if item["level"] == "child"),
        "concepts": len(concept_list),
        "bank_questions": len(bank_matches),
        "session_questions": len(question_matches),
        "sessions": len(session_items),
        "citations": len(citations),
        "provenance": {
            level: provenance.get(level, 0) for level in PROVENANCE_ORDER
        },
    }
    return {
        "type": "material",
        "material": material,
        "history": history,
        "versions": version_rows,
        "chunks": {
            "items": chunks,
            "parents": counts["parents"],
            "children": counts["children"],
        },
        "concepts": concept_list,
        "bank_questions": sorted(
            bank_matches.values(), key=lambda item: item["id"]
        ),
        "session_questions": sorted(
            question_matches.values(), key=lambda item: item["id"], reverse=True
        ),
        "sessions": session_items,
        "citations": list(citations.values()),
        "counts": counts,
        "repair": repair_material(
            material, db_path=db_path
        ),
    }


# ---------------------------------------------------------------------------
# 概念详情
# ---------------------------------------------------------------------------

def concept_detail(
    conn: sqlite3.Connection,
    concepts: Sequence[Concept],
    concept_id: str,
    *,
    db_path: str | Path,
    content_dir: str | Path,
) -> dict[str, Any] | None:
    concepts_by_id = {concept.id: concept for concept in concepts}
    concept = concepts_by_id.get(concept_id)
    state = _state_map(conn).get(concept_id)
    if concept is None and state is None:
        return None

    meta = (
        {
            "id": concept.id,
            "name": concept.name,
            "plain_def": concept.plain_def,
            "aliases": list(concept.aliases),
            "difficulty": concept.difficulty,
            "prerequisites": list(concept.prerequisites),
            "source": {
                "url": concept.source.url,
                "excerpt": concept.source.excerpt,
                "material": concept.source.material,
            },
        }
        if concept is not None
        else {
            "id": concept_id,
            "name": concept_id,
            "plain_def": "",
            "aliases": [],
            "difficulty": None,
            "prerequisites": [],
            "source": None,
        }
    )

    source_rows = _dicts(
        conn.execute(
            """
            SELECT cs.concept_id, cs.chunk_id, cs.excerpt, cs.is_primary,
                   mc.material_id, mc.material_version AS version,
                   mc.heading_path, mc.level,
                   m.title AS material_title, m.path AS material_path,
                   m.version AS current_version
            FROM concept_sources cs
            JOIN material_chunks mc ON mc.id = cs.chunk_id
            LEFT JOIN materials m ON m.id = mc.material_id
            WHERE cs.concept_id = ?
            ORDER BY mc.material_version DESC, cs.is_primary DESC
            """,
            (concept_id,),
        )
    )
    for item in source_rows:
        item["is_current"] = (
            item.get("current_version") is not None
            and int(item["version"]) == int(item["current_version"])
        )

    bank_rows = _dicts(
        conn.execute(
            "SELECT * FROM question_bank WHERE concept_id = ? ORDER BY id",
            (concept_id,),
        )
    )
    material_keys = _material_by_key(_material_rows(conn))
    bank_items = []
    for item in bank_rows:
        material = _match_material(item.get("source_url"), material_keys)
        level = "url" if material is not None else "concept"
        bank_items.append(
            {
                "id": item["id"],
                "kind": item["kind"],
                "question_text": item["question_text"],
                "source_url": item["source_url"],
                "source_excerpt": item["source_excerpt"],
                "material_id": material["id"] if material else None,
                "provenance": _provenance(level),
            }
        )

    question_rows = _dicts(
        conn.execute(
            """
            SELECT q.*, mc.material_id AS chunk_material_id,
                   mc.material_version AS chunk_material_version,
                   mc.heading_path AS chunk_heading_path
            FROM session_questions q
            LEFT JOIN material_chunks mc ON mc.id = q.source_chunk_id
            WHERE q.concept_id = ?
            ORDER BY q.id DESC
            """,
            (concept_id,),
        )
    )
    question_items = []
    for item in question_rows:
        if item.get("chunk_material_id") is not None:
            level = "chunk"
        elif _match_material(item.get("source_url"), material_keys) is not None:
            level = "url"
        else:
            level = "concept"
        question_items.append(
            {
                "id": int(item["id"]),
                "session_id": item["session_id"],
                "question_text": item["question_text"],
                "question_type": item.get("question_type"),
                "score": item.get("score"),
                "answer_text": _preview(item.get("answer_text"), 240),
                "question_bank_id": item.get("question_bank_id"),
                "source_chunk_id": item.get("source_chunk_id"),
                "material_version": item.get("chunk_material_version"),
                "provenance": _provenance(level),
            }
        )

    session_ids = sorted({item["session_id"] for item in question_items})
    sessions = _session_rows(conn, session_ids)
    counts = Counter(item["session_id"] for item in question_items)
    session_items = [
        {**sessions[sid], "question_count": counts[sid]}
        for sid in session_ids
        if sid in sessions
    ]

    dependents = [
        {"id": other.id, "name": other.name}
        for other in concepts
        if concept_id in other.prerequisites
    ]

    return {
        "type": "concept",
        "concept": meta,
        "state": (
            {
                **state,
                "mastery_label": mastery_label(int(state.get("mastery", 0))),
            }
            if state is not None
            else {
                "id": concept_id,
                "mastery": 0,
                "mastery_label": mastery_label(0),
                "status": "proposed",
                "last_seen": None,
                "review_due_at": None,
            }
        ),
        "sources": source_rows,
        "bank_questions": bank_items,
        "session_questions": question_items,
        "sessions": session_items,
        "dependents": dependents,
        "latest_assessment": _latest_assessment(conn, concept_id),
        "counts": {
            "sources": len(source_rows),
            "bank_questions": len(bank_items),
            "session_questions": len(question_items),
            "sessions": len(session_items),
            "dependents": len(dependents),
        },
        "repair": repair_concept(
            meta,
            db_path=db_path,
            content_dir=content_dir,
            sources=source_rows,
        ),
    }


# ---------------------------------------------------------------------------
# 题目详情
# ---------------------------------------------------------------------------

def _question_origin(row: Mapping[str, Any]) -> dict[str, Any]:
    if row.get("question_bank_id"):
        return {"kind": "bank", "label": "题库题", "meta": {}}
    generation_meta = _json(row.get("generation_meta_json"))
    if isinstance(generation_meta, dict) or row.get("source_chunk_id"):
        return {
            "kind": "generated",
            "label": "生成题",
            "meta": generation_meta if isinstance(generation_meta, dict) else {},
        }
    return {"kind": "unknown", "label": "未知来源", "meta": {}}


def _question_provenance(
    row: Mapping[str, Any],
    material_keys: Mapping[str, Mapping[str, Any]],
    chunk: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], Mapping[str, Any] | None]:
    if chunk is not None:
        material = (
            {
                "id": chunk.get("material_id"),
                "title": chunk.get("material_title") or chunk.get("material_id"),
                "path": chunk.get("material_path") or "",
                "version": chunk.get("current_version")
                or chunk.get("material_version"),
            }
            if chunk.get("material_id")
            else None
        )
        return (
            {
                **_provenance("chunk"),
                "material_id": chunk.get("material_id"),
                "material_title": chunk.get("material_title"),
                "material_version": chunk.get("material_version"),
                "chunk_heading": chunk.get("heading_path"),
            },
            material,
        )
    material = _match_material(row.get("source_url"), material_keys)
    if material is not None:
        return (
            {
                **_provenance("url"),
                "material_id": material["id"],
                "material_title": material["title"],
                "material_version": None,
                "chunk_heading": None,
            },
            material,
        )
    if row.get("concept_id"):
        return _provenance("concept"), None
    return _provenance("unmatched"), None


def question_detail(
    conn: sqlite3.Connection,
    concepts: Sequence[Concept],
    *,
    bank_id: str | None = None,
    session_question_id: int | None = None,
    db_path: str | Path,
    content_dir: str | Path,
) -> dict[str, Any] | None:
    concepts_by_id = {concept.id: concept for concept in concepts}
    materials = _material_rows(conn)
    material_keys = _material_by_key(materials)

    if bank_id is not None:
        row = conn.execute(
            "SELECT * FROM question_bank WHERE id = ?", (bank_id,)
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        provenance, material = _question_provenance(item, material_keys)
        usage = _dicts(
            conn.execute(
                """
                SELECT q.id, q.session_id, q.score, q.answer_text, q.created_at,
                       COALESCE(s.date, a.date) AS date,
                       COALESCE(s.status, a.status) AS session_status
                FROM session_questions q
                LEFT JOIN sessions s ON s.id = q.session_id
                LEFT JOIN agent_sessions a ON a.session_id = q.session_id
                WHERE q.question_bank_id = ?
                ORDER BY q.id DESC
                """,
                (bank_id,),
            )
        )
        return {
            "type": "bank_question",
            "question": item,
            "origin": {"kind": "bank", "label": "题库题", "meta": {}},
            "concept": _concept_meta(concepts_by_id, item.get("concept_id")),
            "provenance": provenance,
            "material": dict(material) if material else None,
            "usage": usage,
            "counts": {"usage": len(usage)},
            "repair": repair_bank_question(
                item, db_path=db_path, content_dir=content_dir
            ),
        }

    if session_question_id is None:
        return None
    row = conn.execute(
        "SELECT * FROM session_questions WHERE id = ?",
        (int(session_question_id),),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    chunk = None
    if item.get("source_chunk_id"):
        raw = conn.execute(
            """
            SELECT mc.id, mc.material_id, mc.material_version, mc.heading_path,
                   mc.level, m.title AS material_title, m.path AS material_path,
                   m.version AS current_version
            FROM material_chunks mc
            LEFT JOIN materials m ON m.id = mc.material_id
            WHERE mc.id = ?
            """,
            (item["source_chunk_id"],),
        ).fetchone()
        if raw is not None:
            chunk = dict(raw)
    provenance, material = _question_provenance(item, material_keys, chunk)
    session = _session_rows(conn, [str(item["session_id"])]).get(
        str(item["session_id"])
    )
    origin = _question_origin(item)
    return {
        "type": "session_question",
        "question": item,
        "origin": origin,
        "concept": _concept_meta(concepts_by_id, item.get("concept_id")),
        "provenance": provenance,
        "material": dict(material) if material else None,
        "chunk": chunk,
        "session": session,
        "counts": {"usage": 1},
        "repair": (
            repair_generated_question(item)
            if origin["kind"] == "generated"
            else repair_bank_question(
                {
                    "id": item.get("question_bank_id") or item["id"],
                    "concept_id": item.get("concept_id"),
                    "question_text": item["question_text"],
                },
                db_path=db_path,
                content_dir=content_dir,
            )
        ),
    }


# ---------------------------------------------------------------------------
# 会话 / 自由对话详情
# ---------------------------------------------------------------------------

def session_detail(
    conn: sqlite3.Connection,
    concepts: Sequence[Concept],
    session_id: str,
) -> dict[str, Any] | None:
    concepts_by_id = {concept.id: concept for concept in concepts}
    materials = _material_rows(conn)
    material_keys = _material_by_key(materials)
    session = _session_rows(conn, [session_id]).get(session_id)
    if session is None:
        return None

    questions = _dicts(
        conn.execute(
            """
            SELECT q.*, mc.material_id AS chunk_material_id,
                   mc.material_version AS chunk_material_version,
                   mc.heading_path AS chunk_heading_path
            FROM session_questions q
            LEFT JOIN material_chunks mc ON mc.id = q.source_chunk_id
            WHERE q.session_id = ?
            ORDER BY q.id
            """,
            (session_id,),
        )
    )
    question_items = []
    for item in questions:
        if item.get("chunk_material_id") is not None:
            level = "chunk"
            material = next(
                (
                 candidate
                 for candidate in materials
                 if candidate["id"] == item["chunk_material_id"]
                ),
                None,
            )
        else:
            material = _match_material(item.get("source_url"), material_keys)
            level = "url" if material is not None else (
                "concept" if item.get("concept_id") else "unmatched"
            )
        meta = _concept_meta(concepts_by_id, item.get("concept_id"))
        question_items.append(
            {
                "id": int(item["id"]),
                "concept_id": item.get("concept_id"),
                "concept_name": meta["name"],
                "question_text": item["question_text"],
                "question_type": item.get("question_type"),
                "question_bank_id": item.get("question_bank_id"),
                "score": item.get("score"),
                "answer_text": item.get("answer_text"),
                "feedback": item.get("feedback"),
                "origin": _question_origin(item),
                "provenance": {
                    **_provenance(level),
                    "material_id": material["id"] if material else None,
                    "material_title": material["title"] if material else None,
                    "material_version": item.get("chunk_material_version"),
                    "chunk_heading": item.get("chunk_heading_path"),
                },
            }
        )

    notes = _dicts(
        conn.execute(
            "SELECT * FROM session_notes WHERE session_id = ? ORDER BY id",
            (session_id,),
        )
    )
    return {
        "type": "session",
        "session": session,
        "questions": question_items,
        "notes": notes,
        "counts": {
            "questions": len(question_items),
            "scored": sum(1 for item in question_items if item["score"] is not None),
            "notes": len(notes),
        },
        "repair": repair_session(),
    }


def conversation_detail(
    conn: sqlite3.Connection, conversation_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if row is None:
        return None
    conversation = dict(row)
    materials = _material_rows(conn)
    material_keys = _material_by_key(materials)
    messages = []
    material_count = 0
    web_count = 0
    for message in conn.execute(
        """
        SELECT * FROM conversation_messages
        WHERE conversation_id = ?
        ORDER BY id
        """,
        (conversation_id,),
    ):
        message = dict(message)
        sources = _json(message["sources_json"])
        source_items = []
        if isinstance(sources, list):
            for source in sources:
                if not isinstance(source, dict):
                    continue
                material = _match_material(source.get("url"), material_keys)
                kind = source.get("kind") or (
                    "material" if material is not None else "web"
                )
                if kind == "material":
                    material_count += 1
                else:
                    web_count += 1
                source_items.append(
                    {
                        **source,
                        "kind": kind,
                        "material_id": material["id"] if material else None,
                    }
                )
        messages.append(
            {
                "id": int(message["id"]),
                "role": message["role"],
                "text": message["text"],
                "mode": message.get("mode"),
                "sources": source_items,
                "created_at": message["created_at"],
            }
        )
    return {
        "type": "conversation",
        "conversation": conversation,
        "messages": messages,
        "counts": {
            "messages": len(messages),
            "material_sources": material_count,
            "web_sources": web_count,
        },
        "repair": {
            "type": "conversation",
            "title": "自由对话：历史记录，不可修改",
            "preconditions": [],
            "steps": [],
            "notes": [
                "自由对话消息是历史记录，后台不提供改消息。",
                "引用只到 URL 级：sources_json 没有 chunk_id。",
            ],
        },
    }


# ---------------------------------------------------------------------------
# 健康状态
# ---------------------------------------------------------------------------

def health(
    conn: sqlite3.Connection,
    *,
    db_path: str | Path,
    provider: Mapping[str, Any] | None = None,
    embedding_model: str = "",
    embedding_dim: int = 1024,
) -> dict[str, Any]:
    db_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    path = Path(db_path)
    wal = Path(str(path) + "-wal")
    pipeline_rows = _dicts(
        conn.execute(
            """
            SELECT p.kind, p.status, p.started_at, p.finished_at, p.input,
                   p.error, p.stats_json
            FROM pipeline_runs p
            JOIN (
              SELECT kind, MAX(id) AS max_id
              FROM pipeline_runs GROUP BY kind
            ) latest ON latest.kind = p.kind AND latest.max_id = p.id
            ORDER BY p.kind
            """
        )
    )
    for item in pipeline_rows:
        item["stats"] = _json(item.get("stats_json"))
        item.pop("stats_json", None)

    missing_embeddings = conn.execute(
        """
        SELECT COUNT(*)
        FROM material_chunks c
        JOIN materials m ON m.id = c.material_id AND m.version = c.material_version
        LEFT JOIN chunk_embeddings e
          ON e.chunk_id = c.id AND e.model = ? AND e.dim = ?
        WHERE c.level = 'child' AND m.status = 'active' AND e.chunk_id IS NULL
        """,
        (embedding_model, embedding_dim),
    ).fetchone()[0]
    missing_fts = conn.execute(
        """
        SELECT COUNT(*)
        FROM material_chunks c
        JOIN materials m ON m.id = c.material_id AND m.version = c.material_version
        WHERE c.level = 'child' AND m.status = 'active'
          AND NOT EXISTS (SELECT 1 FROM chunk_fts f WHERE f.chunk_id = c.id)
        """
    ).fetchone()[0]
    orphan_embeddings = conn.execute(
        """
        SELECT COUNT(*) FROM chunk_embeddings e
        WHERE NOT EXISTS (SELECT 1 FROM material_chunks c WHERE c.id = e.chunk_id)
        """
    ).fetchone()[0]
    orphan_fts = conn.execute(
        """
        SELECT COUNT(*) FROM chunk_fts f
        WHERE NOT EXISTS (SELECT 1 FROM material_chunks c WHERE c.id = f.chunk_id)
        """
    ).fetchone()[0]

    red: list[dict[str, Any]] = []
    yellow: list[dict[str, Any]] = []
    if db_version != SCHEMA_VERSION:
        red.append(
            {
                "code": "db_version",
                "message": (
                    f"数据库 user_version={db_version}，代码支持 {SCHEMA_VERSION}；"
                    "请确认分支与库。"
                ),
            }
        )
    provider_payload = dict(provider or {})
    if provider_payload.get("fake"):
        red.append(
            {
                "code": "provider_fake",
                "message": (
                    "至少一个 provider 在 fake 模式："
                    f"{provider_payload.get('modes') or {}}"
                ),
            }
        )
    for item in pipeline_rows:
        if item["status"] in ("failed", "partial"):
            red.append(
                {
                    "code": f"pipeline_{item['kind']}",
                    "message": (
                        f"{item['kind']} 最近一次 {item['status']}："
                        f"{item.get('error') or '无错误信息'}"
                    ),
                }
            )
    if missing_embeddings or missing_fts or orphan_embeddings or orphan_fts:
        yellow.append(
            {
                "code": "index",
                "message": (
                    f"索引待补：embedding {missing_embeddings}，FTS {missing_fts}；"
                    f"孤儿行 embedding {orphan_embeddings}，FTS {orphan_fts}。"
                ),
            }
        )

    return {
        "ok": not red,
        "red": red,
        "yellow": yellow,
        "db": {
            "path": _db_path(path),
            "version": db_version,
            "schema_version": SCHEMA_VERSION,
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "wal_size_bytes": wal.stat().st_size if wal.exists() else 0,
        },
        "provider": provider_payload,
        "pipelines": pipeline_rows,
        "index": {
            "model": embedding_model,
            "dim": embedding_dim,
            "missing_embeddings": missing_embeddings,
            "missing_fts": missing_fts,
            "orphan_embeddings": orphan_embeddings,
            "orphan_fts": orphan_fts,
        },
        "counts": {
            "materials": conn.execute(
                "SELECT COUNT(*) FROM materials WHERE status = 'active'"
            ).fetchone()[0],
            "chunks": conn.execute(
                """
                SELECT COUNT(*) FROM material_chunks c
                JOIN materials m ON m.id = c.material_id
                 AND m.version = c.material_version
                WHERE m.status = 'active'
                """
            ).fetchone()[0],
            "concepts": conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0],
            "bank_questions": conn.execute(
                "SELECT COUNT(*) FROM question_bank"
            ).fetchone()[0],
            "sessions": conn.execute(
                "SELECT COUNT(*) FROM agent_sessions"
            ).fetchone()[0],
            "conversations": conn.execute(
                "SELECT COUNT(*) FROM conversations"
            ).fetchone()[0],
        },
    }


def _db_path(path: Path) -> str:
    try:
        return path.resolve().as_posix()
    except OSError:
        return path.as_posix()
