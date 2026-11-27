from __future__ import annotations

from fastapi.testclient import TestClient

from bff.config import load_settings
from bff.main import create_app
from core.db import connect, init_schema
from core.ports import SearchHit
from core.store import Store

MATERIAL_TEXT = "模型自作主张会加需求，像点清汤面却端来加料版。"


def make_env(tmp_path) -> dict[str, str]:
    return {
        "PROVIDER_MODE": "fake",
        "DB_PATH": str(tmp_path / "app.db"),
        "DATA_DIR": str(tmp_path / "data"),
        "CONTENT_DIR": str(tmp_path),
        "RETRIEVAL_MIN_COSINE": "1.0",
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
                    "text": MATERIAL_TEXT,
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


class TopicSearch:
    name = "topic-search"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        self.calls.append(query)
        if any(word in query for word in ("最新", "今天", "现在")):
            return [
                SearchHit(
                    title="时效结果",
                    url="https://example.com/time",
                    content=query + " " + "时效正文" * 40,
                    score=0.9,
                    published_at="2026-11-24",
                )
            ]
        if "区块链" in query:
            return [
                SearchHit(
                    title="区块链说明",
                    url="https://example.com/blockchain",
                    content="区块链是一种分布式账本。" * 20,
                    score=0.9,
                    published_at=None,
                )
            ]
        return []


def recv_until(ws, wanted: str, limit: int = 80) -> dict:
    for _ in range(limit):
        message = ws.receive_json()
        if message.get("type") == wanted:
            return message
    raise AssertionError(f"没有收到 {wanted}")


def test_ten_web_search_scenarios(tmp_path) -> None:
    seed_material(tmp_path / "app.db")
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        search = TopicSearch()
        app.state.providers.search = search
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            conversation_id = None

            def ask(text: str) -> dict:
                nonlocal conversation_id
                before = len(search.calls)
                payload = {"type": "text", "text": text, "turn_id": text}
                if conversation_id:
                    payload["conversation_id"] = conversation_id
                ws.send_json(payload)
                reply = recv_until(ws, "reply")
                conversation_id = reply["conversation_id"]
                reply["_search_calls"] = len(search.calls) - before
                return reply

            material_questions = [
                "模型自作主张",
                "模型自作主张 是什么",
                "模型自作主张 解释",
                "模型自作主张 举例",
                "模型自作主张 workflow 区别",
            ]
            for question in material_questions:
                reply = ask(question)
                assert reply["_search_calls"] == 0, question
                assert reply["web_status"] == "off", question
                assert reply["sources"], question
                assert all(source["kind"] == "material" for source in reply["sources"])

            time_questions = [
                "最新的 agent 版本",
                "今天 agent 有什么新闻",
                "现在 agent 的价格",
            ]
            for question in time_questions:
                reply = ask(question)
                assert reply["_search_calls"] == 1, question
                assert reply["web_status"] == "ok", question
                assert any(source["kind"] == "web" for source in reply["sources"])
                assert reply["sources"][0]["published_at"] == "2026-11-24"
                assert reply["sources"][0]["retrieved_at"]

            blockchain = ask("什么是区块链")
            assert blockchain["_search_calls"] == 1
            assert blockchain["web_status"] == "ok"
            assert blockchain["sources"][0]["kind"] == "web"
            assert blockchain["sources"][0]["published_at"] is None

            quantum = ask("量子计算是什么")
            assert quantum["_search_calls"] == 1
            assert quantum["web_status"] == "empty"
            assert quantum["sources"] == []
            assert quantum["text"].startswith("材料里没有直接讲到，联网也没查到")


def test_empty_search_query_skips_search(tmp_path) -> None:
    seed_material(tmp_path / "app.db")
    env = make_env(tmp_path)
    env["RETRIEVAL_MIN_COSINE"] = "1.1"
    app = create_app(load_settings(env))
    with TestClient(app) as client:
        search = TopicSearch()
        app.state.providers.search = search
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "text", "text": "联网查一下"})
            reply = recv_until(ws, "reply")
            assert search.calls == []
            assert reply["web_status"] == "empty"
            assert reply["sources"] == []
            assert reply["text"].startswith("材料里没有直接讲到，联网也没查到")
