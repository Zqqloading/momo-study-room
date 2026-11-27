from __future__ import annotations

from fastapi.testclient import TestClient

from bff.config import load_settings
from bff.main import create_app
from core.db import connect, init_schema
from core.ports import SearchHit
from core.store import Store


def make_env(tmp_path) -> dict[str, str]:
    return {
        "PROVIDER_MODE": "fake",
        "DB_PATH": str(tmp_path / "app.db"),
        "DATA_DIR": str(tmp_path / "data"),
        "CONTENT_DIR": str(tmp_path),
    }


def seed_material(db_path) -> None:
    store = Store(connect(db_path))
    try:
        init_schema(store.conn)
        store.upsert_material(
            material_id="m",
            title="示例材料",
            path="materials/note.md",
            format="md",
            content_hash="h1",
            version=1,
            added_at="2026-11-24T00:00:00",
            status="active",
            source_url="local://materials/note.md",
            tags_json=None,
        )
        store.insert_chunks(
            [
                {
                    "id": "m-v1-child-001",
                    "material_id": "m",
                    "material_version": 1,
                    "parent_id": None,
                    "level": "child",
                    "heading_path": "模型自作主张",
                    "text": "模型自作主张会自作主张加需求。",
                    "content_hash": "c1",
                    "token_count": 10,
                    "ordinal": 1,
                    "source_url": "local://materials/note.md",
                }
            ]
        )
        store.rebuild_fts()
    finally:
        store.close()


class ScriptedSearch:
    name = "scripted-search"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        return [
            SearchHit(
                title="网页结果",
                url="https://example.com/a",
                content="agent 最新版本 " + "正文" * 50,
                score=0.9,
                published_at="2026-11-20",
            )
        ]


def recv_until(ws, wanted: str, limit: int = 60) -> dict:
    for _ in range(limit):
        message = ws.receive_json()
        if message.get("type") == wanted:
            return message
    raise AssertionError(f"没有收到 {wanted}")


def test_web_sources_do_not_touch_knowledge_tables(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    seed_material(db_path)
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        app.state.providers.search = ScriptedSearch()
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {"type": "text", "text": "最新的 agent 版本", "turn_id": "t1"}
            )
            reply = recv_until(ws, "reply")
            assert reply["sources"]
            assert reply["sources"][0]["kind"] == "web"

            check = connect(db_path)
            try:
                assert (
                    check.execute("SELECT COUNT(*) FROM session_questions").fetchone()[0]
                    == 0
                )
            finally:
                check.close()

            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = recv_until(ws, "session_ready")
            question_text = ready["question"]["text"]
            assert "agent 最新版本" not in question_text
            assert "正文" not in question_text

    conn = connect(db_path)
    try:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "materials",
                "concept_sources",
                "hot_items",
                "session_questions",
            )
        }
    finally:
        conn.close()
    assert counts == {
        "materials": 1,
        "concept_sources": 0,
        "hot_items": 0,
        "session_questions": 5,
    }
