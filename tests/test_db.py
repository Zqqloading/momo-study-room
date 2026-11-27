from __future__ import annotations

import sqlite3

import pytest

from core.db import SCHEMA_VERSION, connect, init_schema

KB_TABLES = {"materials", "material_chunks", "concept_sources", "question_cache"}
RETRIEVAL_TABLES = {"chunk_embeddings", "chunk_fts"}
PIPELINE_TABLES = {"pipeline_runs"}
HOT_TABLES = {"hot_items", "hot_fts"}
AFFECT_TABLES = {"emotion_states", "user_memories", "user_memories_fts", "memory_runs"}
ADMIN_TASK_TABLES = {"admin_tasks"}

TABLES = {
    "concepts",
    "question_bank",
    "sessions",
    "session_concepts",
    "session_questions",
    "misconceptions",
    "agent_sessions",
    "session_notes",
    "conversations",
    "conversation_messages",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_schema_creates_all_tables() -> None:
    conn = connect(":memory:")
    try:
        init_schema(conn)
        names = _table_names(conn)
        assert TABLES <= names
        assert KB_TABLES <= names
        assert RETRIEVAL_TABLES <= names
        assert PIPELINE_TABLES <= names
        assert HOT_TABLES <= names
        assert AFFECT_TABLES <= names
        assert ADMIN_TASK_TABLES <= names
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert SCHEMA_VERSION == 8
        assert {
            "question_type",
            "source_chunk_id",
            "generation_meta_json",
        } <= _column_names(conn, "session_questions")
    finally:
        conn.close()


def test_conversation_messages_has_sources_json() -> None:
    conn = connect(":memory:")
    try:
        init_schema(conn)
        assert "sources_json" in _column_names(conn, "conversation_messages")
    finally:
        conn.close()


def test_v1_rebuilds_older_database() -> None:
    conn = connect(":memory:")
    try:
        init_schema(conn)
        conn.execute("INSERT INTO concepts (id, mastery, status) VALUES ('old', 0, 'active')")
        conn.execute("PRAGMA user_version = 1")
        init_schema(conn)
        assert conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 0
    finally:
        conn.close()


def test_v3_agent_db_gets_knowledge_tables(tmp_path) -> None:
    """progress 的 v3 库只有会话/对话表，启动后要补齐 KB 表。"""
    conn = connect(tmp_path / "agent-v3.db")
    try:
        init_schema(conn)
        for table in sorted(KB_TABLES | RETRIEVAL_TABLES | PIPELINE_TABLES | HOT_TABLES):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA user_version = 3")

        init_schema(conn)

        names = _table_names(conn)
        assert KB_TABLES <= names
        assert RETRIEVAL_TABLES <= names
        assert PIPELINE_TABLES <= names
        assert HOT_TABLES <= names
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        conn.close()


def test_v3_kb_db_gets_agent_tables(tmp_path) -> None:
    """KB 的 v3 库只有内容/检索表，启动后要补齐会话与对话表。"""
    conn = connect(tmp_path / "kb-v3.db")
    try:
        init_schema(conn)
        for table in sorted(TABLES):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA user_version = 3")

        init_schema(conn)

        names = _table_names(conn)
        assert TABLES <= names
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        conn.close()


def test_v4_adds_sources_json_column(tmp_path) -> None:
    """v4 库的 conversation_messages 没有 sources_json，v5 只补这一列。"""
    conn = connect(tmp_path / "v4.db")
    try:
        init_schema(conn)
        conn.execute("DROP TABLE conversation_messages")
        conn.execute(
            """
            CREATE TABLE conversation_messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              conversation_id TEXT NOT NULL,
              role TEXT NOT NULL CHECK (role IN ('user','assistant')),
              text TEXT NOT NULL,
              mode TEXT,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("PRAGMA user_version = 4")

        init_schema(conn)

        assert "sources_json" in _column_names(conn, "conversation_messages")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        conn.close()


def test_v5_adds_question_provenance_columns(tmp_path) -> None:
    """v5 库的 session_questions 没有出题溯源三列，v6 只补列且旧行可读。"""
    conn = connect(tmp_path / "v5.db")
    try:
        init_schema(conn)
        conn.execute("DROP TABLE session_questions")
        conn.execute(
            """
            CREATE TABLE session_questions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              concept_id TEXT,
              question_bank_id TEXT,
              question_role TEXT NOT NULL CHECK (question_role IN ('new','review','retention','misconception')),
              kind TEXT NOT NULL,
              question_text TEXT NOT NULL,
              rubric_json TEXT NOT NULL,
              options_json TEXT,
              answer_key TEXT,
              answer_text TEXT,
              score INTEGER CHECK (score BETWEEN 0 AND 100),
              feedback TEXT,
              misconception_id INTEGER,
              source_url TEXT NOT NULL,
              source_excerpt TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO session_questions
              (session_id, question_role, kind, question_text, rubric_json,
               source_url, source_excerpt, created_at)
            VALUES ('s-old', 'new', 'recall', '旧题', '{}', 'u', 'e', 't')
            """
        )
        conn.execute("PRAGMA user_version = 5")

        init_schema(conn)

        assert {
            "question_type",
            "source_chunk_id",
            "generation_meta_json",
        } <= _column_names(conn, "session_questions")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        row = conn.execute(
            """
            SELECT question_text, question_type, source_chunk_id, generation_meta_json
            FROM session_questions WHERE session_id = 's-old'
            """
        ).fetchone()
        assert row["question_text"] == "旧题"
        assert row["question_type"] is None
        assert row["source_chunk_id"] is None
        assert row["generation_meta_json"] is None
        conn.execute(
            """
            UPDATE session_questions
            SET question_type = 'concept', source_chunk_id = 'm-v1-child-001',
                generation_meta_json = '{"origin": "generated"}'
            WHERE session_id = 's-old'
            """
        )
    finally:
        conn.close()


def test_v6_db_gets_affect_tables_without_touching_old_tables(tmp_path) -> None:
    """v6 库只有旧表；v7 只加四张新表，旧数据原样保留。"""
    conn = connect(tmp_path / "v6.db")
    try:
        init_schema(conn)
        conn.execute(
            "INSERT INTO concepts (id, mastery, status) VALUES ('old', 2, 'active')"
        )
        for table in sorted(AFFECT_TABLES):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA user_version = 6")

        init_schema(conn)

        names = _table_names(conn)
        assert AFFECT_TABLES <= names
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        row = conn.execute(
            "SELECT mastery, status FROM concepts WHERE id = 'old'"
        ).fetchone()
        assert (row["mastery"], row["status"]) == (2, "active")
        assert {
            "user_id",
            "role",
            "comfort",
            "energy",
            "updated_at",
        } <= _column_names(conn, "emotion_states")
    finally:
        conn.close()


def test_v7_db_gets_admin_tasks_without_touching_old_tables(tmp_path) -> None:
    """v7 库只有旧表；v8 只加 admin_tasks，旧数据原样保留。"""
    conn = connect(tmp_path / "v7.db")
    try:
        init_schema(conn)
        conn.execute(
            "INSERT INTO concepts (id, mastery, status) VALUES ('old', 3, 'active')"
        )
        conn.execute("DROP TABLE admin_tasks")
        conn.execute("PRAGMA user_version = 7")

        init_schema(conn)

        names = _table_names(conn)
        assert ADMIN_TASK_TABLES <= names
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        row = conn.execute(
            "SELECT mastery, status FROM concepts WHERE id = 'old'"
        ).fetchone()
        assert (row["mastery"], row["status"]) == (3, "active")
        assert {
            "id",
            "kind",
            "status",
            "params_json",
            "progress_json",
            "result_json",
            "log_text",
            "error",
            "created_at",
            "started_at",
            "finished_at",
        } <= _column_names(conn, "admin_tasks")
    finally:
        conn.close()


def test_schema_narrows_session_kind() -> None:
    conn = connect(":memory:")
    try:
        init_schema(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO sessions
                  (id, date, kind, status, started_at, input_mode, created_at)
                VALUES ('s1', '2026-11-23', 'diagnostic', 'completed', 'x', 'text', 'x')
                """
            )
    finally:
        conn.close()


def test_schema_allows_retention_question_role() -> None:
    conn = connect(":memory:")
    try:
        init_schema(conn)
        conn.execute(
            """
            INSERT INTO session_questions
              (session_id, question_role, kind, question_text, rubric_json,
               source_url, source_excerpt, created_at)
            VALUES ('s1', 'retention', 'recall', 'q', '{}', 'u', 'e', 't')
            """
        )
    finally:
        conn.close()


def test_init_schema_rejects_newer_version() -> None:
    conn = connect(":memory:")
    try:
        init_schema(conn)
        conn.execute("PRAGMA user_version = 99")
        with pytest.raises(RuntimeError, match="拒绝打开"):
            init_schema(conn)
    finally:
        conn.close()


def test_connect_creates_parent_directory(tmp_path) -> None:
    path = tmp_path / "nested" / "app.db"
    conn = connect(path)
    try:
        init_schema(conn)
        assert path.exists()
    finally:
        conn.close()
