"""SQLite 读写：逐题落库即时 commit，会话结算单事务（D5）。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterable, Iterator, Mapping

from .models import (
    ConceptAssessment,
    ConceptState,
    HotItem,
    SessionRecord,
    SessionResult,
)

_QUESTION_KINDS = {"recall", "discriminate", "apply"}
_QUESTION_ROLES = {"new", "review", "misconception"}
_BANK_REQUIRED = (
    "id",
    "concept_id",
    "kind",
    "question_text",
    "rubric_json",
    "source_url",
    "source_excerpt",
)


class SessionAlreadyFinalized(RuntimeError):
    """同一 session 已经结算过，拒绝重复写分。"""


def _json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _normalize_hot_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _age_days(captured_at: str, now: str) -> int:
    try:
        delta = datetime.fromisoformat(now) - datetime.fromisoformat(captured_at)
    except ValueError:
        return 0
    return max(0, delta.days)


def _fts_match(query: str) -> str | None:
    terms = [term for term in query.split() if term]
    if not terms:
        return None
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)


def _short_terms(query: str) -> list[str]:
    """trigram 对少于 3 个字符的中文词不命中，这些词走子串回退。"""
    return [term for term in query.split() if 0 < len(term) < 3]


def _bigrams(query: str) -> list[str]:
    """无空格中文线索的 2 字回退；trigram 命中不了 2 字词。"""
    terms: list[str] = []
    for index in range(len(query) - 1):
        term = query[index : index + 2]
        if term not in terms:
            terms.append(term)
    return terms


def _meaningful_user_text(text: str) -> bool:
    clean = " ".join((text or "").split())
    if len(clean) < 4:
        return False
    return clean not in {"不知道", "不清楚", "不会", "不懂", "跳过", "随便", "忘了"}


def _hot_item(row: Mapping[str, Any], now: str) -> HotItem:
    return HotItem(
        id=int(row["id"]),
        source_kind=str(row["source_kind"]),
        text=str(row["text"]),
        content_hash=str(row["content_hash"]),
        captured_at=str(row["captured_at"]),
        last_seen=str(row["last_seen"]),
        seen_count=int(row["seen_count"]),
        title=row["title"],
        source_url=row["source_url"],
        expires_at=row["expires_at"],
        status=str(row["status"]),
        material_id=row["material_id"],
        verified=False,
        age_days=_age_days(str(row["captured_at"]), now),
    )


_BANK_FIELDS = (
    "concept_id",
    "kind",
    "question_text",
    "rubric_json",
    "options_json",
    "answer_key",
    "source_url",
    "source_excerpt",
)


def _bank_row_differs(existing: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    return any(existing.get(key) != row.get(key) for key in _BANK_FIELDS)


class Store:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator["Store"]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    # ---- concepts ----

    def upsert_concept(self, state: ConceptState) -> None:
        self.conn.execute(
            """
            INSERT INTO concepts
              (id, mastery, status, prior_status, last_seen, review_started_at, review_due_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              mastery = excluded.mastery,
              status = excluded.status,
              prior_status = excluded.prior_status,
              last_seen = excluded.last_seen,
              review_started_at = excluded.review_started_at,
              review_due_at = excluded.review_due_at
            """,
            (
                state.id,
                state.mastery,
                state.status,
                state.prior_status,
                state.last_seen,
                state.review_started_at,
                state.review_due_at,
            ),
        )

    def concept_states(self) -> list[ConceptState]:
        rows = self.conn.execute("SELECT * FROM concepts ORDER BY id").fetchall()
        return [ConceptState(**dict(row)) for row in rows]

    def concept_state(self, concept_id: str) -> ConceptState | None:
        row = self.conn.execute("SELECT * FROM concepts WHERE id = ?", (concept_id,)).fetchone()
        return ConceptState(**dict(row)) if row else None

    def due_reviews(self, today: str) -> list[ConceptState]:
        rows = self.conn.execute(
            """
            SELECT * FROM concepts
            WHERE review_due_at IS NOT NULL AND review_due_at <= ?
              AND status = 'active'
            ORDER BY review_due_at, id
            """,
            (today,),
        ).fetchall()
        return [ConceptState(**dict(row)) for row in rows]

    # ---- materials / chunks ----

    def material_by_path(self, path: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM materials WHERE path = ?", (path,)
        ).fetchone()
        return dict(row) if row else None

    def material_by_id(self, material_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM materials WHERE id = ?", (material_id,)
        ).fetchone()
        return dict(row) if row else None

    def has_materials(self) -> bool:
        row = self.conn.execute("SELECT 1 FROM materials LIMIT 1").fetchone()
        return row is not None

    def material_chunks(self, material_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, level, heading_path, text FROM material_chunks
            WHERE material_id = ?
            ORDER BY material_version DESC, ordinal
            """,
            (material_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def material_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM materials
            WHERE content_hash = ?
            ORDER BY added_at DESC, id
            LIMIT 1
            """,
            (content_hash,),
        ).fetchone()
        return dict(row) if row else None

    def upsert_material(
        self,
        *,
        material_id: str,
        title: str,
        path: str,
        format: str,
        content_hash: str,
        version: int,
        added_at: str,
        status: str,
        source_url: str | None,
        tags_json: str | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO materials
              (id, title, path, format, content_hash, version, added_at,
               status, source_url, tags_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title = excluded.title,
              path = excluded.path,
              format = excluded.format,
              content_hash = excluded.content_hash,
              version = excluded.version,
              added_at = excluded.added_at,
              status = excluded.status,
              source_url = excluded.source_url,
              tags_json = excluded.tags_json
            """,
            (
                material_id,
                title,
                path,
                format,
                content_hash,
                version,
                added_at,
                status,
                source_url,
                tags_json,
            ),
        )

    def upsert_concept_source(
        self,
        *,
        concept_id: str,
        chunk_id: str,
        excerpt: str,
        is_primary: bool = True,
    ) -> None:
        if is_primary:
            self.conn.execute(
                "UPDATE concept_sources SET is_primary = 0 "
                "WHERE concept_id = ? AND chunk_id <> ?",
                (concept_id, chunk_id),
            )
        self.conn.execute(
            """
            INSERT INTO concept_sources (concept_id, chunk_id, excerpt, is_primary)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(concept_id, chunk_id) DO UPDATE SET
              excerpt = excluded.excerpt,
              is_primary = excluded.is_primary
            """,
            (concept_id, chunk_id, excerpt, 1 if is_primary else 0),
        )

    def insert_chunks(self, rows: Iterable[Mapping[str, Any]]) -> int:
        payload = [
            (
                str(row["id"]),
                str(row["material_id"]),
                int(row["material_version"]),
                row.get("parent_id"),
                str(row["level"]),
                row.get("heading_path"),
                str(row["text"]),
                str(row["content_hash"]),
                int(row["token_count"]),
                int(row["ordinal"]),
                str(row["source_url"]),
            )
            for row in rows
        ]
        if not payload:
            return 0
        before = self.conn.total_changes
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO material_chunks
              (id, material_id, material_version, parent_id, level, heading_path,
               text, content_hash, token_count, ordinal, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        return self.conn.total_changes - before

    def missing_chunk_ids(self, chunk_ids: Iterable[str]) -> list[str]:
        ids = list(dict.fromkeys(str(chunk_id) for chunk_id in chunk_ids))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT id FROM material_chunks WHERE id IN ({placeholders})", ids
        ).fetchall()
        found = {row["id"] for row in rows}
        return [chunk_id for chunk_id in ids if chunk_id not in found]

    # ---- retrieval indexes ----

    def rebuild_fts(self) -> int:
        rows = self.conn.execute(
            """
            SELECT c.id, c.material_id, c.material_version, c.heading_path, c.text
            FROM material_chunks c
            JOIN materials m ON m.id = c.material_id AND m.version = c.material_version
            WHERE c.level = 'child' AND m.status = 'active'
            """
        ).fetchall()
        self.conn.execute("DELETE FROM chunk_fts")
        self.conn.executemany(
            """
            INSERT INTO chunk_fts (chunk_id, material_id, material_version, text)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    row["id"],
                    row["material_id"],
                    row["material_version"],
                    (row["heading_path"] + "\n" if row["heading_path"] else "") + row["text"],
                )
                for row in rows
            ],
        )
        return len(rows)

    def search_fts(self, query: str, limit: int = 20) -> list[tuple[str, float]]:
        safe = _fts_match(query)
        rows: list[tuple[str, float]] = []
        if safe is not None:
            found = self.conn.execute(
                """
                SELECT f.chunk_id, bm25(chunk_fts) AS score
                FROM chunk_fts f
                JOIN material_chunks c ON c.id = f.chunk_id
                JOIN materials m ON m.id = c.material_id AND m.version = c.material_version
                WHERE chunk_fts MATCH ? AND m.status = 'active' AND c.level = 'child'
                ORDER BY score
                LIMIT ?
                """,
                (safe, limit),
            ).fetchall()
            rows = [(row["chunk_id"], float(row["score"])) for row in found]

        short = _short_terms(query)
        if short:
            seen = {chunk_id for chunk_id, _ in rows}
            for row in self._short_term_rows(short, limit):
                if row["id"] in seen:
                    continue
                rows.append((str(row["id"]), -float(row["hits"])))
        return rows[:limit]

    def _short_term_rows(
        self, terms: list[str], limit: int
    ) -> list[sqlite3.Row]:
        score_expr = " + ".join(["(instr(lower(text), lower(?)) > 0)"] * len(terms))
        sql = f"""
        WITH body AS (
          SELECT c.id, COALESCE(c.heading_path, '') || char(10) || c.text AS text
          FROM material_chunks c
          JOIN materials m ON m.id = c.material_id AND m.version = c.material_version
          WHERE c.level = 'child' AND m.status = 'active'
        )
        SELECT id, {score_expr} AS hits
        FROM body
        WHERE {score_expr} > 0
        ORDER BY hits DESC, id
        LIMIT ?
        """
        return self.conn.execute(sql, [*terms, *terms, limit]).fetchall()

    def latest_child_chunks(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT c.* FROM material_chunks c
            JOIN materials m ON m.id = c.material_id AND m.version = c.material_version
            WHERE c.level = 'child' AND m.status = 'active'
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert_embedding(
        self,
        *,
        chunk_id: str,
        model: str,
        dim: int,
        vector: bytes,
        created_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO chunk_embeddings (chunk_id, model, dim, vector, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
              model = excluded.model,
              dim = excluded.dim,
              vector = excluded.vector,
              created_at = excluded.created_at
            """,
            (chunk_id, model, dim, vector, created_at),
        )

    def embeddings_latest(self, model: str, dim: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT e.chunk_id, e.vector
            FROM chunk_embeddings e
            JOIN material_chunks c ON c.id = e.chunk_id
            JOIN materials m ON m.id = c.material_id AND m.version = c.material_version
            WHERE c.level = 'child' AND m.status = 'active'
              AND e.model = ? AND e.dim = ?
            """,
            (model, dim),
        ).fetchall()
        return [dict(row) for row in rows]

    def missing_embedding_chunks(self, model: str, dim: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT c.id, c.heading_path, c.text, c.content_hash
            FROM material_chunks c
            JOIN materials m ON m.id = c.material_id AND m.version = c.material_version
            LEFT JOIN chunk_embeddings e
              ON e.chunk_id = c.id AND e.model = ? AND e.dim = ?
            WHERE c.level = 'child' AND m.status = 'active' AND e.chunk_id IS NULL
            """,
            (model, dim),
        ).fetchall()
        return [dict(row) for row in rows]

    def embedding_by_content_hash(
        self, content_hash: str, model: str, dim: int, heading_path: str
    ) -> bytes | None:
        row = self.conn.execute(
            """
            SELECT e.vector
            FROM chunk_embeddings e
            JOIN material_chunks c ON c.id = e.chunk_id
            WHERE c.content_hash = ? AND e.model = ? AND e.dim = ?
              AND COALESCE(c.heading_path, '') = ?
            LIMIT 1
            """,
            (content_hash, model, dim, heading_path),
        ).fetchone()
        return row["vector"] if row else None

    def prune_index_orphans(self) -> tuple[int, int]:
        embeddings = self.conn.execute(
            """
            DELETE FROM chunk_embeddings
            WHERE chunk_id NOT IN (SELECT id FROM material_chunks)
            """
        ).rowcount
        fts = self.conn.execute(
            """
            DELETE FROM chunk_fts
            WHERE chunk_id NOT IN (SELECT id FROM material_chunks)
            """
        ).rowcount
        return embeddings, fts

    def chunk_with_parent(self, chunk_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT c.id AS child_id, c.text AS child_text, c.source_url AS child_url,
                   c.parent_id AS parent_id, c.heading_path AS child_heading,
                   p.id AS parent_chunk_id, p.text AS parent_text,
                   p.source_url AS parent_url, p.heading_path AS parent_heading
            FROM material_chunks c
            LEFT JOIN material_chunks p ON p.id = c.parent_id
            WHERE c.id = ?
            """,
            (chunk_id,),
        ).fetchone()
        return dict(row) if row else None

    def concept_id_for_chunk(self, chunk_id: str) -> str | None:
        rows = self.conn.execute(
            """
            SELECT DISTINCT cs.concept_id
            FROM concept_sources cs
            JOIN material_chunks c ON c.id = ?
            WHERE cs.chunk_id IN (c.id, c.parent_id)
            """,
            (chunk_id,),
        ).fetchall()
        # 同一父块挂多个概念时无法判断归属，返回 None，由调用方传 concept_id。
        return rows[0]["concept_id"] if len(rows) == 1 else None

    def concept_source_excerpt(self, concept_id: str) -> str | None:
        row = self.conn.execute(
            """
            SELECT excerpt FROM concept_sources
            WHERE concept_id = ?
            ORDER BY is_primary DESC, chunk_id
            LIMIT 1
            """,
            (concept_id,),
        ).fetchone()
        return row["excerpt"] if row else None

    def primary_concept_source(self, concept_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM concept_sources
            WHERE concept_id = ?
            ORDER BY is_primary DESC, chunk_id
            LIMIT 1
            """,
            (concept_id,),
        ).fetchone()
        return dict(row) if row else None

    # ---- question bank ----

    def import_question_bank(
        self, rows: Iterable[Mapping[str, Any]], *, allow_empty: bool = False
    ) -> int:
        """全量镜像同步：upsert seeds 行 + 删除 seeds 中不存在的 id。

        返回新增 + 更新 + 删除的行数；与库里完全一致的重复导入返回 0。
        空输入默认拒绝，避免误用空 seeds 清空题库；确实要清空请传
        ``allow_empty=True``。删除不回写 ``session_questions``：其
        ``question_bank_id`` 作为历史 id 保留，回放不依赖它（KB-18）。
        """
        payload: list[dict[str, Any]] = []
        for row in rows:
            missing = [key for key in _BANK_REQUIRED if not row.get(key)]
            if missing:
                raise ValueError(f"题库行缺字段 {missing}: {row!r}")
            kind = str(row["kind"])
            if kind not in _QUESTION_KINDS:
                raise ValueError(f"题库行 kind 不合法：{kind!r}")
            payload.append(
                {
                    "id": str(row["id"]),
                    "concept_id": str(row["concept_id"]),
                    "kind": kind,
                    "question_text": str(row["question_text"]),
                    "rubric_json": _json(row["rubric_json"]),
                    "options_json": _json(row.get("options_json")),
                    "answer_key": row.get("answer_key"),
                    "source_url": str(row["source_url"]),
                    "source_excerpt": str(row["source_excerpt"]),
                }
            )

        ids = [row["id"] for row in payload]
        if len(ids) != len(set(ids)):
            raise ValueError("题库 id 重复")

        inserted = updated = deleted = 0
        with self.transaction():
            existing = {
                row["id"]: dict(row)
                for row in self.conn.execute("SELECT * FROM question_bank")
            }
            if not payload and not allow_empty and existing:
                raise ValueError(
                    "拒绝用空题库清空镜像；确实要清空请传 allow_empty=True"
                )
            wanted = set(ids)
            stale = [row_id for row_id in existing if row_id not in wanted]
            for row in payload:
                current = existing.get(row["id"])
                if current is None:
                    self.conn.execute(
                        """
                        INSERT INTO question_bank
                          (id, concept_id, kind, question_text, rubric_json, options_json,
                           answer_key, source_url, source_excerpt)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["id"],
                            row["concept_id"],
                            row["kind"],
                            row["question_text"],
                            row["rubric_json"],
                            row["options_json"],
                            row["answer_key"],
                            row["source_url"],
                            row["source_excerpt"],
                        ),
                    )
                    inserted += 1
                elif _bank_row_differs(current, row):
                    self.conn.execute(
                        """
                        UPDATE question_bank SET
                          concept_id = ?, kind = ?, question_text = ?, rubric_json = ?,
                          options_json = ?, answer_key = ?, source_url = ?, source_excerpt = ?
                        WHERE id = ?
                        """,
                        (
                            row["concept_id"],
                            row["kind"],
                            row["question_text"],
                            row["rubric_json"],
                            row["options_json"],
                            row["answer_key"],
                            row["source_url"],
                            row["source_excerpt"],
                            row["id"],
                        ),
                    )
                    updated += 1

            if stale:
                marks = ",".join("?" * len(stale))
                deleted = self.conn.execute(
                    f"DELETE FROM question_bank WHERE id IN ({marks})", stale
                ).rowcount
            else:
                deleted = 0

        return inserted + updated + deleted

    def bank_question(self, question_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM question_bank WHERE id = ?", (question_id,)
        ).fetchone()
        return dict(row) if row else None

    def bank_questions(self, concept_id: str) -> list[dict[str, Any]]:
        """某概念的全部题库题，按 id 稳定排序，供 Planner/Coach 选题。"""
        rows = self.conn.execute(
            "SELECT * FROM question_bank WHERE concept_id = ? ORDER BY id",
            (concept_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def question_usage(self, concept_id: str) -> dict[str, int]:
        """题库 id → 最近一次被插入会话的 session_questions.id（越大越新）。"""
        rows = self.conn.execute(
            """
            SELECT question_bank_id, MAX(id) AS last_id
            FROM session_questions
            WHERE concept_id = ? AND question_bank_id IS NOT NULL
            GROUP BY question_bank_id
            """,
            (concept_id,),
        ).fetchall()
        return {str(row["question_bank_id"]): int(row["last_id"]) for row in rows}

    def previous_question_texts(self, concept_id: str, limit: int = 10) -> list[str]:
        """该概念最近出现的题干，新→旧；供生成器做去重负样本。"""
        rows = self.conn.execute(
            """
            SELECT question_text FROM session_questions
            WHERE concept_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (concept_id, limit),
        ).fetchall()
        return [str(row["question_text"]) for row in rows]

    # ---- session questions ----

    def add_question(
        self,
        *,
        session_id: str,
        question_bank_id: str | None,
        concept_id: str | None,
        role: str,
        kind: str,
        text: str,
        rubric_json: Any,
        source_url: str,
        source_excerpt: str,
        created_at: str,
        options_json: Any = None,
        answer_key: str | None = None,
        question_type: str | None = None,
        source_chunk_id: str | None = None,
        generation_meta_json: Any = None,
    ) -> int:
        if role not in _QUESTION_ROLES:
            raise ValueError(f"question_role 不合法：{role!r}")
        if kind not in _QUESTION_KINDS:
            raise ValueError(f"kind 不合法：{kind!r}")
        if not source_url or not source_excerpt:
            raise ValueError("每道题必须带 source_url 与 source_excerpt")

        cursor = self.conn.execute(
            """
            INSERT INTO session_questions
              (session_id, concept_id, question_bank_id, question_role, kind,
               question_type, question_text, rubric_json, options_json, answer_key,
               source_url, source_excerpt, source_chunk_id, generation_meta_json,
               created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                concept_id,
                question_bank_id,
                role,
                kind,
                question_type,
                text,
                _json(rubric_json),
                _json(options_json),
                answer_key,
                source_url,
                source_excerpt,
                source_chunk_id,
                _json(generation_meta_json),
                created_at,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def save_answer(
        self,
        question_id: int,
        *,
        text: str | None,
        score: int | None,
        feedback: str | None,
    ) -> None:
        if score is not None and not 0 <= score <= 100:
            raise ValueError(f"score 越界：{score}")
        cursor = self.conn.execute(
            "UPDATE session_questions SET answer_text = ?, score = ?, feedback = ? WHERE id = ?",
            (text, score, feedback, question_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"session_questions 不存在：{question_id}")
        self.conn.commit()

    def question(self, question_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM session_questions WHERE id = ?", (question_id,)
        ).fetchone()
        return dict(row) if row else None

    def session_questions(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM session_questions WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def recent_concept_scores(
        self, concept_id: str, *, limit: int = 3, exclude_session: str | None = None
    ) -> list[float]:
        """该概念最近几次 daily 的 concept_session_score（role=new 的均分）。

        不含当前未结算场；返回按日期倒序，供 mastery 取最近三次。
        """
        params: list[Any] = [concept_id]
        exclude = ""
        if exclude_session:
            exclude = "AND s.id != ?"
            params.append(exclude_session)
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT AVG(q.score) AS avg_score
            FROM session_questions q
            JOIN sessions s ON s.id = q.session_id
            WHERE q.concept_id = ?
              AND q.question_role = 'new'
              AND q.score IS NOT NULL
              AND s.kind = 'daily'
              AND s.status = 'completed'
              {exclude}
            GROUP BY s.id
            ORDER BY s.date DESC, s.created_at DESC, s.id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return [float(row["avg_score"]) for row in rows if row["avg_score"] is not None]

    def latest_concept_assessments(
        self, concept_ids: Iterable[str] | None = None
    ) -> dict[str, ConceptAssessment]:
        """每个概念最近一次有评分的作答；含未结算/abandoned 会话。

        只看 `score IS NOT NULL`；同一场里该概念的所有角色一起算均分与最低分。
        最近一场全是未评分时自然跳过，回退到上一场有评分的会话。
        """
        ids = None if concept_ids is None else list(concept_ids)
        if ids is not None and not ids:
            return {}

        where = "q.score IS NOT NULL AND COALESCE(s.date, a.date) IS NOT NULL"
        params: list[Any] = []
        if ids is not None:
            placeholders = ",".join("?" for _ in ids)
            where += f" AND q.concept_id IN ({placeholders})"
            params.extend(ids)

        rows = self.conn.execute(
            f"""
            SELECT q.concept_id AS concept_id,
                   COALESCE(s.date, a.date) AS date,
                   q.session_id AS session_id,
                   AVG(q.score) AS avg_score,
                   MIN(q.score) AS min_score,
                   COUNT(*) AS scored
            FROM session_questions q
            LEFT JOIN agent_sessions a ON a.session_id = q.session_id
            LEFT JOIN sessions s ON s.id = q.session_id
            WHERE {where}
            GROUP BY q.session_id, q.concept_id
            ORDER BY date DESC,
                     COALESCE(a.started_at, s.started_at) DESC,
                     q.session_id DESC
            """,
            tuple(params),
        ).fetchall()

        latest: dict[str, ConceptAssessment] = {}
        for row in rows:
            concept_id = str(row["concept_id"])
            if concept_id in latest:
                continue
            latest[concept_id] = ConceptAssessment(
                concept_id=concept_id,
                date=str(row["date"]),
                session_id=str(row["session_id"]),
                avg_score=float(row["avg_score"]),
                min_score=float(row["min_score"]),
                scored=int(row["scored"]),
            )
        return latest

    # ---- agent sessions ----

    def start_agent_session(
        self,
        *,
        session_id: str,
        kind: str,
        date: str,
        started_at: str,
        concept_id: str | None = None,
        input_mode: str = "text",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO agent_sessions
              (session_id, kind, date, started_at, updated_at, status,
               concept_id, input_mode)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (session_id, kind, date, started_at, started_at, concept_id, input_mode),
        )
        self.conn.commit()

    def agent_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def touch_agent_session(
        self,
        session_id: str,
        *,
        last_question_id: int | None,
        input_mode: str,
        updated_at: str,
    ) -> None:
        cursor = self.conn.execute(
            """
            UPDATE agent_sessions
            SET last_question_id = ?, input_mode = ?, updated_at = ?
            WHERE session_id = ?
            """,
            (last_question_id, input_mode, updated_at, session_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"agent_sessions 不存在：{session_id}")
        self.conn.commit()

    def abandon_stale_agent_sessions(self, *, today: str, updated_at: str) -> int:
        cursor = self.conn.execute(
            """
            UPDATE agent_sessions SET status = 'abandoned', updated_at = ?
            WHERE status = 'active' AND date < ?
            """,
            (updated_at, today),
        )
        self.conn.commit()
        return cursor.rowcount

    def first_unanswered_question(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM session_questions
            WHERE session_id = ? AND answer_text IS NULL AND score IS NULL
            ORDER BY id
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    # ---- session notes ----

    def add_session_note(
        self,
        *,
        session_id: str,
        question_id: int | None,
        mode: str,
        input_text: str,
        output_text: str,
        created_at: str,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO session_notes
              (session_id, question_id, mode, input_text, output_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, question_id, mode, input_text, output_text, created_at),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def session_notes(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM session_notes WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    # ---- conversations ----

    def create_conversation(
        self, *, conversation_id: str, created_at: str, title: str | None = None
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO conversations (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, title, created_at, created_at),
        )
        self.conn.commit()

    def conversation(self, conversation_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return dict(row) if row else None

    def latest_conversation(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC, id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        self.conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title, conversation_id),
        )
        self.conn.commit()

    def delete_conversation(self, conversation_id: str) -> None:
        self.conn.execute(
            "DELETE FROM conversation_messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        self.conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        self.conn.commit()

    def conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN conversation_messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC, c.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def append_conversation_message(
        self,
        *,
        conversation_id: str,
        role: str,
        text: str,
        created_at: str,
        mode: str | None = None,
        sources: list[dict[str, Any]] | None = None,
    ) -> int:
        if role not in ("user", "assistant"):
            raise ValueError(f"role 不合法：{role!r}")
        if self.conversation(conversation_id) is None:
            raise KeyError(f"conversations 不存在：{conversation_id}")

        cursor = self.conn.execute(
            """
            INSERT INTO conversation_messages
              (conversation_id, role, text, mode, sources_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                role,
                text,
                mode,
                _json(sources) if sources else None,
                created_at,
            ),
        )
        title = text.strip()[:24] if role == "user" else None
        self.conn.execute(
            """
            UPDATE conversations
            SET updated_at = ?, title = COALESCE(title, ?)
            WHERE id = ?
            """,
            (created_at, title or None, conversation_id),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def conversation_messages(
        self, conversation_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        if limit is None:
            rows = self.conn.execute(
                """
                SELECT * FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY id
                """,
                (conversation_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM (
                  SELECT * FROM conversation_messages
                  WHERE conversation_id = ?
                  ORDER BY id DESC
                  LIMIT ?
                ) ORDER BY id
                """,
                (conversation_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_conversation_messages(
        self, conversation_id: str, limit: int = 12
    ) -> list[dict[str, Any]]:
        return self.conversation_messages(conversation_id, limit=limit)

    # ---- session finalize ----

    def finalize(
        self,
        record: SessionRecord,
        result: SessionResult,
        *,
        agent_session_id: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        if record.session_id != result.session_id:
            raise ValueError("record 与 result 的 session_id 不一致")
        if record.status != result.status:
            raise ValueError("record.status 与 result.status 不一致")

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self.conn.execute(
                "SELECT status FROM sessions WHERE id = ?", (record.session_id,)
            ).fetchone()
            if existing and existing["status"] != "unscored":
                raise SessionAlreadyFinalized(f"session 已结算：{record.session_id}")

            for concept_id in result.mastery_updates:
                row = self.conn.execute(
                    "SELECT 1 FROM concepts WHERE id = ?", (concept_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"concept 不存在：{concept_id}")
            for score in result.scores:
                row = self.conn.execute(
                    "SELECT session_id FROM session_questions WHERE id = ?",
                    (int(score.question_id),),
                ).fetchone()
                if row is None or row["session_id"] != record.session_id:
                    raise ValueError(f"question 不属于该 session：{score.question_id}")

            values = (
                record.date,
                record.concept_id,
                record.kind,
                record.status,
                record.started_at,
                record.minutes,
                record.asr_text,
                record.explained_text,
                record.input_mode,
                record.asr_confidence,
                record.session_score,
                record.created_at,
            )
            if existing:
                self.conn.execute(
                    """
                    UPDATE sessions SET
                      date = ?, concept_id = ?, kind = ?, status = ?, started_at = ?,
                      minutes = ?, asr_text = ?, explained_text = ?, input_mode = ?,
                      asr_confidence = ?, session_score = ?, created_at = ?
                    WHERE id = ?
                    """,
                    (*values, record.session_id),
                )
            else:
                self.conn.execute(
                    """
                    INSERT INTO sessions
                      (date, concept_id, kind, status, started_at, minutes,
                       asr_text, explained_text, input_mode, asr_confidence,
                       session_score, created_at, id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*values, record.session_id),
                )

            for score in result.scores:
                self.conn.execute(
                    """
                    UPDATE session_questions
                    SET score = ?, feedback = ?
                    WHERE id = ? AND session_id = ?
                    """,
                    (score.score, score.why, int(score.question_id), record.session_id),
                )

            due_updates = dict(result.due_updates)
            if not due_updates and result.concept_id and result.mastery_updates:
                # 兼容旧调用：没有 due_updates 时，单概念结果仍写到 concept_id。
                due_updates[result.concept_id] = (
                    result.review_due_at,
                    result.review_started_at,
                )

            for concept_id, mastery in result.mastery_updates.items():
                sets = ["mastery = ?", "last_seen = ?"]
                params: list[Any] = [mastery, record.date]
                if concept_id in due_updates:
                    due, started = due_updates[concept_id]
                    sets += ["review_due_at = ?", "review_started_at = ?"]
                    params += [due, started]
                self.conn.execute(
                    f"UPDATE concepts SET {', '.join(sets)} WHERE id = ?",
                    (*params, concept_id),
                )
                self.conn.execute(
                    "INSERT OR IGNORE INTO session_concepts (session_id, concept_id) VALUES (?, ?)",
                    (record.session_id, concept_id),
                )

            for concept_id, (due, started) in due_updates.items():
                if concept_id in result.mastery_updates:
                    continue
                self.conn.execute(
                    """
                    UPDATE concepts
                    SET review_due_at = ?, review_started_at = ?, last_seen = ?
                    WHERE id = ?
                    """,
                    (due, started, record.date, concept_id),
                )
                self.conn.execute(
                    "INSERT OR IGNORE INTO session_concepts (session_id, concept_id) VALUES (?, ?)",
                    (record.session_id, concept_id),
                )

            if agent_session_id is not None:
                cursor = self.conn.execute(
                    """
                    UPDATE agent_sessions SET status = 'finished', updated_at = ?
                    WHERE session_id = ?
                    """,
                    (finished_at or record.created_at, agent_session_id),
                )
                if cursor.rowcount == 0:
                    raise KeyError(f"agent_sessions 不存在：{agent_session_id}")

            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def session(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def recent_sessions(self, limit: int = 3) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT date, kind, status, session_score
            FROM sessions
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def recent_units(self, limit: int = 5) -> list[dict[str, Any]]:
        """最近会话及其涉及的概念 id；用于知识库面板的单元历史。"""
        rows = self.conn.execute(
            """
            SELECT s.id AS session_id, s.date, s.kind, s.status, s.session_score,
                   GROUP_CONCAT(DISTINCT q.concept_id) AS concept_ids
            FROM sessions s
            LEFT JOIN session_questions q ON q.session_id = s.id
            GROUP BY s.id
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        units: list[dict[str, Any]] = []
        for row in rows:
            unit = dict(row)
            raw = unit.pop("concept_ids") or ""
            unit["concept_ids"] = tuple(part for part in raw.split(",") if part)
            units.append(unit)
        return units

    def answered_questions_since(
        self, since: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """某个时间点之后已评分的题（含会话信息）；用于前端「答题记录」。"""
        rows = self.conn.execute(
            """
            SELECT q.id, q.session_id, q.concept_id, q.question_role, q.question_type,
                   q.kind, q.question_text, q.answer_text, q.score, q.feedback,
                   q.created_at, substr(q.created_at, 1, 10) AS session_date,
                   s.kind AS session_kind
            FROM session_questions q
            LEFT JOIN sessions s ON s.id = q.session_id
            WHERE q.score IS NOT NULL AND q.created_at >= ?
            ORDER BY q.created_at DESC, q.id DESC
            LIMIT ?
            """,
            (since, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    # ---- emotion ----

    def emotion_state(
        self, user_id: str, role: str, *, now: str | None = None
    ) -> dict[str, Any]:
        """读情绪行；首次读自动建中间态默认行。"""
        created_at = now or _now()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO emotion_states
              (user_id, role, comfort, energy, updated_at)
            VALUES (?, ?, 0, 0.5, ?)
            """,
            (user_id, role, created_at),
        )
        row = self.conn.execute(
            """
            SELECT comfort, energy, updated_at
            FROM emotion_states
            WHERE user_id = ? AND role = ?
            """,
            (user_id, role),
        ).fetchone()
        return dict(row)

    def save_emotion_state(
        self,
        user_id: str,
        role: str,
        comfort: float,
        energy: float,
        updated_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO emotion_states (user_id, role, comfort, energy, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, role) DO UPDATE SET
              comfort = excluded.comfort,
              energy = excluded.energy,
              updated_at = excluded.updated_at
            """,
            (user_id, role, comfort, energy, updated_at),
        )

    # ---- user memory ----

    def add_user_memory(
        self,
        *,
        user_id: str,
        kind: str,
        text: str,
        source_quote: str,
        source_session_id: str | None,
        source_question_id: int | None,
        strength: float,
        half_life_days: float,
        last_recalled_at: str,
        created_at: str,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO user_memories
              (user_id, kind, text, source_quote, source_session_id,
               source_question_id, strength, half_life_days,
               last_recalled_at, recall_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                user_id,
                kind,
                text,
                source_quote,
                source_session_id,
                source_question_id,
                strength,
                half_life_days,
                last_recalled_at,
                created_at,
            ),
        )
        memory_id = int(cursor.lastrowid)
        self.conn.execute(
            """
            INSERT INTO user_memories_fts (memory_id, text, source_quote)
            VALUES (?, ?, ?)
            """,
            (str(memory_id), text, source_quote),
        )
        return memory_id

    def user_memories(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM user_memories WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def update_memory_recall(
        self,
        memory_id: int,
        *,
        strength: float,
        half_life_days: float,
        last_recalled_at: str,
        recall_count: int,
    ) -> None:
        self.conn.execute(
            """
            UPDATE user_memories
            SET strength = ?, half_life_days = ?, last_recalled_at = ?,
                recall_count = ?
            WHERE id = ?
            """,
            (strength, half_life_days, last_recalled_at, recall_count, memory_id),
        )

    def search_user_memories(
        self, user_id: str, query: str, limit: int = 3
    ) -> list[dict[str, Any]]:
        """FTS5 trigram；无命中时按 2 字子串回退。包含沉底记忆。"""
        safe = _fts_match(query)
        rows: list[dict[str, Any]] = []
        if safe is not None:
            found = self.conn.execute(
                """
                SELECT m.*, -bm25(user_memories_fts) AS score
                FROM user_memories_fts f
                JOIN user_memories m ON m.id = f.memory_id
                WHERE user_memories_fts MATCH ? AND m.user_id = ?
                ORDER BY bm25(user_memories_fts)
                LIMIT ?
                """,
                (safe, user_id, limit * 3),
            ).fetchall()
            rows = [dict(row) for row in found]

        if not rows:
            terms = _bigrams(query)
            if terms:
                score_expr = " + ".join(
                    ["(instr(lower(m.text), lower(?)) > 0) + "
                     "(instr(lower(m.source_quote), lower(?)) > 0)"]
                    * len(terms)
                )
                params: list[Any] = []
                for term in terms:
                    params.extend([term, term])
                params.extend([user_id, limit * 3])
                found = self.conn.execute(
                    f"""
                    WITH scored AS (
                      SELECT m.*, {score_expr} AS hits
                      FROM user_memories m
                      WHERE m.user_id = ?
                    )
                    SELECT * FROM scored WHERE hits > 0
                    ORDER BY hits DESC, last_recalled_at ASC, id ASC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
                rows = [dict(row) for row in found]
                for row in rows:
                    row["score"] = float(row.get("hits") or 0)
        return rows[: limit * 3]

    def rebuild_user_memory_fts(self) -> int:
        rows = self.conn.execute(
            "SELECT id, text, source_quote FROM user_memories"
        ).fetchall()
        self.conn.execute("DELETE FROM user_memories_fts")
        self.conn.executemany(
            """
            INSERT INTO user_memories_fts (memory_id, text, source_quote)
            VALUES (?, ?, ?)
            """,
            [(str(row["id"]), row["text"], row["source_quote"]) for row in rows],
        )
        return len(rows)

    def memory_run_for_session(
        self, user_id: str, session_id: str
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM memory_runs
            WHERE user_id = ? AND session_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, session_id),
        ).fetchone()
        return dict(row) if row else None

    def memory_run_exists(self, user_id: str, session_id: str) -> bool:
        return self.memory_run_for_session(user_id, session_id) is not None

    def start_memory_run(
        self, *, user_id: str, session_id: str, started_at: str
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO memory_runs (user_id, session_id, status, started_at)
            VALUES (?, ?, 'running', ?)
            """,
            (user_id, session_id, started_at),
        )
        return int(cursor.lastrowid)

    def finish_memory_run(
        self,
        run_id: int,
        *,
        status: str,
        memory_count: int,
        error: str | None,
        finished_at: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE memory_runs
            SET status = ?, memory_count = ?, error = ?, finished_at = ?
            WHERE id = ?
            """,
            (status, memory_count, error, finished_at, run_id),
        )

    def user_texts_for_session(self, session_id: str) -> list[dict[str, Any]]:
        """提炼输入：作答 + probe/teach_back 笔记；不含 assistant 文本。"""
        questions = self.session_questions(session_id)
        question_texts = {
            row["id"]: row["question_text"] for row in questions
        }
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()

        def push(text: str, question_id: int | None) -> None:
            clean = " ".join(text.split())
            if not _meaningful_user_text(clean) or clean in seen:
                return
            seen.add(clean)
            rows.append(
                {
                    "text": text.strip(),
                    "question_id": question_id,
                    "question_text": question_texts.get(question_id),
                }
            )

        for question in questions:
            push(str(question.get("answer_text") or ""), question["id"])
        for note in self.session_notes(session_id):
            if note["mode"] not in ("probe", "teach_back"):
                continue
            push(str(note.get("input_text") or ""), note.get("question_id"))
        return rows

    # ---- pipeline runs ----

    def start_pipeline_run(self, kind: str, input: str | None = None) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """
            UPDATE pipeline_runs
            SET status = 'failed', finished_at = ?, error = 'aborted'
            WHERE kind = ? AND status = 'running'
            """,
            (now, kind),
        )
        cursor = self.conn.execute(
            "INSERT INTO pipeline_runs (kind, started_at, status, input) VALUES (?, ?, 'running', ?)",
            (kind, now, input),
        )
        return int(cursor.lastrowid)

    def finish_pipeline_run(
        self,
        run_id: int,
        status: str,
        stats: Mapping[str, Any] | None = None,
        *,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE pipeline_runs
            SET finished_at = ?, status = ?, stats_json = ?, error = ?
            WHERE id = ?
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                status,
                _json(stats),
                error,
                run_id,
            ),
        )

    # ---- hot items ----

    def capture_hot_item(
        self,
        *,
        source_kind: str,
        text: str,
        text_origin: str,
        title: str | None = None,
        source_url: str | None = None,
        ttl_days: int = 7,
    ) -> int:
        if source_kind not in {"session", "agent"}:
            raise ValueError(f"未知的热项来源：{source_kind}")
        if text_origin not in {"user", "question"}:
            raise ValueError("热项只接受用户输入或会话问题文本")
        normalized = _normalize_hot_text(text)
        if not normalized:
            raise ValueError("热项文本为空")
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        now = _now()
        existing = self.conn.execute(
            "SELECT id FROM hot_items WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if existing is not None:
            self.conn.execute(
                "UPDATE hot_items SET last_seen = ?, seen_count = seen_count + 1 WHERE id = ?",
                (now, existing["id"]),
            )
            return int(existing["id"])

        expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat(
            timespec="seconds"
        )
        cursor = self.conn.execute(
            """
            INSERT INTO hot_items
              (source_kind, source_url, title, text, content_hash,
               captured_at, last_seen, seen_count, expires_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 'hot')
            """,
            (source_kind, source_url, title, normalized, content_hash, now, now, expires_at),
        )
        self.rebuild_hot_fts()
        return int(cursor.lastrowid)

    def hot_item(self, hot_id: int) -> HotItem | None:
        row = self.conn.execute(
            "SELECT * FROM hot_items WHERE id = ?", (hot_id,)
        ).fetchone()
        return _hot_item(row, _now()) if row else None

    def list_hot_items(self, limit: int = 20) -> list[HotItem]:
        now = _now()
        rows = self.conn.execute(
            """
            SELECT * FROM hot_items
            WHERE status = 'hot' AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY id DESC LIMIT ?
            """,
            (now, limit),
        ).fetchall()
        return [_hot_item(row, now) for row in rows]

    def hot_items_for_query(self, query: str, limit: int = 3) -> list[HotItem]:
        safe = _fts_match(query)
        if safe is None:
            return []
        now = _now()
        rows = self.conn.execute(
            """
            SELECT h.*, bm25(hot_fts) AS score
            FROM hot_fts f
            JOIN hot_items h ON h.id = f.hot_id
            WHERE hot_fts MATCH ? AND h.status = 'hot'
              AND (h.expires_at IS NULL OR h.expires_at > ?)
            ORDER BY score
            LIMIT ?
            """,
            (safe, now, limit),
        ).fetchall()
        return [_hot_item(row, now) for row in rows]

    def discard_hot_item(self, hot_id: int) -> bool:
        cursor = self.conn.execute(
            """
            UPDATE hot_items SET status = 'discarded', last_seen = ?
            WHERE id = ? AND status = 'hot'
            """,
            (_now(), hot_id),
        )
        if cursor.rowcount:
            self.rebuild_hot_fts()
        return bool(cursor.rowcount)

    def expire_hot_items(self, now: str | None = None) -> int:
        stamp = now or _now()
        cursor = self.conn.execute(
            """
            UPDATE hot_items SET status = 'expired', last_seen = ?
            WHERE status = 'hot' AND expires_at IS NOT NULL AND expires_at <= ?
            """,
            (stamp, stamp),
        )
        if cursor.rowcount:
            self.rebuild_hot_fts()
        return cursor.rowcount

    def mark_hot_promoted(self, hot_id: int, material_id: str) -> bool:
        cursor = self.conn.execute(
            """
            UPDATE hot_items
            SET status = 'promoted', material_id = ?, last_seen = ?
            WHERE id = ? AND status = 'hot'
            """,
            (material_id, _now(), hot_id),
        )
        if cursor.rowcount:
            self.rebuild_hot_fts()
        return bool(cursor.rowcount)

    def rebuild_hot_fts(self) -> int:
        rows = self.conn.execute(
            "SELECT id AS hot_id, COALESCE(title, '') AS title, text FROM hot_items"
        ).fetchall()
        self.conn.execute("DELETE FROM hot_fts")
        self.conn.executemany(
            "INSERT INTO hot_fts (hot_id, title, text) VALUES (?, ?, ?)",
            [(row["hot_id"], row["title"], row["text"]) for row in rows],
        )
        return len(rows)
