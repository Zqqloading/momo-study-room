"""SQLite schema 与连接。

v5 合并 agent 会话与知识库检索：v2 的 agent 会话表、v3 的 conversations、
KB 的 materials/chunks/索引表、hot/pipeline 表全部幂等建表；
conversation_messages 在 v5 追加 sources_json。
v6 给 session_questions 追加出题溯源三列。
v7 新增情绪状态、用户记忆与记忆提炼审计四张表；高于当前版本拒绝打开。
v8 新增管理后台长任务表 admin_tasks；只加表，不改旧表。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 8

# v1 重建时按依赖倒序删除；v1 没有后续新表，IF EXISTS 兜底。
_DROP_ORDER = (
    "hot_fts",
    "hot_items",
    "chunk_fts",
    "chunk_embeddings",
    "pipeline_runs",
    "question_cache",
    "concept_sources",
    "material_chunks",
    "materials",
    "conversation_messages",
    "conversations",
    "session_notes",
    "agent_sessions",
    "misconceptions",
    "session_questions",
    "session_concepts",
    "sessions",
    "question_bank",
    "concepts",
)

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS concepts (
  id TEXT PRIMARY KEY,
  mastery INTEGER NOT NULL DEFAULT 0 CHECK (mastery BETWEEN 0 AND 5),
  status TEXT NOT NULL CHECK (status IN ('proposed','active','known','skipped','orphaned')),
  prior_status TEXT,
  last_seen TEXT,
  review_started_at TEXT,
  review_due_at TEXT
);

CREATE TABLE IF NOT EXISTS question_bank (
  id TEXT PRIMARY KEY,
  concept_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('recall','discriminate','apply')),
  question_text TEXT NOT NULL,
  rubric_json TEXT NOT NULL,
  options_json TEXT,
  answer_key TEXT,
  source_url TEXT NOT NULL,
  source_excerpt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  concept_id TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('daily','review')),
  status TEXT NOT NULL CHECK (status IN ('completed','partial','unscored')),
  started_at TEXT NOT NULL,
  minutes INTEGER,
  asr_text TEXT,
  explained_text TEXT,
  input_mode TEXT NOT NULL CHECK (input_mode IN ('voice','text')),
  asr_confidence REAL,
  session_score REAL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_concepts (
  session_id TEXT NOT NULL,
  concept_id TEXT NOT NULL,
  PRIMARY KEY (session_id, concept_id)
);

CREATE TABLE IF NOT EXISTS session_questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  concept_id TEXT,
  question_bank_id TEXT,
  question_role TEXT NOT NULL CHECK (question_role IN ('new','review','retention','misconception')),
  kind TEXT NOT NULL,
  question_type TEXT,
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
  source_chunk_id TEXT,
  generation_meta_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS misconceptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  concept_id TEXT NOT NULL,
  key TEXT NOT NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('candidate','active','resolved')),
  times_seen INTEGER NOT NULL DEFAULT 1,
  clean_streak INTEGER NOT NULL DEFAULT 0,
  last_seen TEXT,
  UNIQUE (concept_id, key)
);

CREATE TABLE IF NOT EXISTS agent_sessions (
  session_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('daily','review')),
  date TEXT NOT NULL,
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active','finished','abandoned')),
  concept_id TEXT,
  last_question_id INTEGER,
  input_mode TEXT NOT NULL DEFAULT 'text' CHECK (input_mode IN ('voice','text'))
);

CREATE TABLE IF NOT EXISTS session_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  question_id INTEGER,
  mode TEXT NOT NULL CHECK (mode IN ('probe','teach_back')),
  input_text TEXT NOT NULL,
  output_text TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  title TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user','assistant')),
  text TEXT NOT NULL,
  mode TEXT,
  sources_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages
  ON conversation_messages(conversation_id, id);

CREATE INDEX IF NOT EXISTS idx_session_questions_session ON session_questions(session_id);
CREATE INDEX IF NOT EXISTS idx_question_bank_concept ON question_bank(concept_id);
CREATE INDEX IF NOT EXISTS idx_concepts_due ON concepts(review_due_at);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_date ON agent_sessions(date, status);
CREATE INDEX IF NOT EXISTS idx_session_notes_session ON session_notes(session_id);
"""

KB_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS materials (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  format TEXT NOT NULL CHECK (format IN ('md','html')),
  content_hash TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  added_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active','missing')),
  source_url TEXT,
  tags_json TEXT
);

CREATE TABLE IF NOT EXISTS material_chunks (
  id TEXT PRIMARY KEY,
  material_id TEXT NOT NULL,
  material_version INTEGER NOT NULL,
  parent_id TEXT,
  level TEXT NOT NULL CHECK (level IN ('parent','child')),
  heading_path TEXT,
  text TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  token_count INTEGER NOT NULL,
  ordinal INTEGER NOT NULL,
  source_url TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS concept_sources (
  concept_id TEXT NOT NULL,
  chunk_id TEXT NOT NULL,
  excerpt TEXT NOT NULL,
  is_primary INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (concept_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS question_cache (
  concept_id TEXT NOT NULL,
  target_date TEXT NOT NULL,
  slot INTEGER NOT NULL CHECK (slot BETWEEN 1 AND 5),
  question_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  review_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (review_status IN ('pending','passed','flagged','promoted','rejected','rolled_back')),
  reviewer TEXT,
  reason TEXT,
  reviewed_at TEXT,
  promoted_at TEXT,
  PRIMARY KEY (concept_id, target_date, slot)
);

CREATE INDEX IF NOT EXISTS idx_material_chunks_material
  ON material_chunks(material_id, material_version);
CREATE INDEX IF NOT EXISTS idx_material_chunks_parent ON material_chunks(parent_id);
CREATE INDEX IF NOT EXISTS idx_concept_sources_concept ON concept_sources(concept_id);
CREATE INDEX IF NOT EXISTS idx_question_cache_due
  ON question_cache(target_date, review_status);
"""

RETRIEVAL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chunk_embeddings (
  chunk_id TEXT PRIMARY KEY,
  model TEXT NOT NULL,
  dim INTEGER NOT NULL,
  vector BLOB NOT NULL,
  created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
  chunk_id UNINDEXED,
  material_id UNINDEXED,
  material_version UNINDEXED,
  text,
  tokenize='trigram'
);
"""

PIPELINE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK (kind IN ('ingest','extract','confirm','reindex')),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed','partial')),
  input TEXT,
  stats_json TEXT,
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_kind_started
  ON pipeline_runs(kind, started_at);
"""

HOT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS hot_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_kind TEXT NOT NULL CHECK (source_kind IN ('session','agent')),
  source_url TEXT,
  title TEXT,
  text TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  captured_at TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  seen_count INTEGER NOT NULL DEFAULT 1,
  expires_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('hot','promoted','discarded','expired')),
  material_id TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS hot_fts USING fts5(
  hot_id UNINDEXED,
  title,
  text,
  tokenize='trigram'
);
"""

# v7：情绪状态、用户记忆、记忆提炼审计。只加表，不改旧表。
AFFECT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS emotion_states (
  user_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'learner',
  comfort REAL NOT NULL CHECK (comfort BETWEEN -1 AND 1),
  energy REAL NOT NULL CHECK (energy BETWEEN 0 AND 1),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, role)
);

CREATE TABLE IF NOT EXISTS user_memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('quote','preference','feeling')),
  text TEXT NOT NULL,
  source_quote TEXT NOT NULL,
  source_session_id TEXT,
  source_question_id INTEGER,
  strength REAL NOT NULL,
  half_life_days REAL NOT NULL DEFAULT 14.0,
  last_recalled_at TEXT NOT NULL,
  recall_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS user_memories_fts USING fts5(
  memory_id UNINDEXED,
  text,
  source_quote,
  tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS memory_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('running','succeeded','empty','failed')),
  memory_count INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_memories_last_recalled
  ON user_memories(last_recalled_at);
CREATE INDEX IF NOT EXISTS idx_user_memories_kind
  ON user_memories(kind);
CREATE INDEX IF NOT EXISTS idx_memory_runs_session
  ON memory_runs(session_id);
"""

# v8：管理后台长任务。只加表，不改旧表。
ADMIN_TASK_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS admin_tasks (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('ingest','rebuild','evaluate')),
  status TEXT NOT NULL CHECK (
    status IN ('queued','running','succeeded','failed','cancelled','awaiting_review')
  ),
  params_json TEXT NOT NULL,
  progress_json TEXT,
  result_json TEXT,
  log_text TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_admin_tasks_status
  ON admin_tasks(status, created_at);
"""

def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, ddl: str
) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def connect(path: str | Path) -> sqlite3.Connection:
    """打开连接。文件库自动建父目录；:memory: 用于测试。"""
    if isinstance(path, Path) and str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"数据库版本 {version} 高于代码支持的 {SCHEMA_VERSION}；拒绝打开"
        )
    # v1 的 CHECK 约束需要重建；v2+ 只补缺失的表与列。
    if version == 1:
        for table in _DROP_ORDER:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript(SCHEMA_SQL)
    conn.executescript(KB_SCHEMA_SQL)
    conn.executescript(RETRIEVAL_SCHEMA_SQL)
    conn.executescript(PIPELINE_SCHEMA_SQL)
    conn.executescript(HOT_SCHEMA_SQL)
    conn.executescript(AFFECT_SCHEMA_SQL)
    conn.executescript(ADMIN_TASK_SCHEMA_SQL)
    _ensure_column(
        conn, "conversation_messages", "sources_json", "sources_json TEXT"
    )
    _ensure_column(conn, "session_questions", "question_type", "question_type TEXT")
    _ensure_column(
        conn, "session_questions", "source_chunk_id", "source_chunk_id TEXT"
    )
    _ensure_column(
        conn, "session_questions", "generation_meta_json", "generation_meta_json TEXT"
    )
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
