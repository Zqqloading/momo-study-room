from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from bff.config import load_settings
from bff.main import create_app
from core.db import connect
from core.store import Store


def make_env(tmp_path) -> dict[str, str]:
    return {
        "PROVIDER_MODE": "fake",
        "DB_PATH": str(tmp_path / "app.db"),
        "DATA_DIR": str(tmp_path / "data"),
        "CONTENT_DIR": str(tmp_path),
    }


def _recv_until(ws, wanted: str, limit: int = 80) -> dict:
    for _ in range(limit):
        message = ws.receive_json()
        if message["type"] == wanted:
            return message
    raise AssertionError(f"没有等到 {wanted}")


def _answer_one_question(client: TestClient) -> dict:
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "session_start", "kind": "daily"})
        ready = _recv_until(ws, "session_ready")
        question = ready["question"]
        ws.send_json(
            {
                "type": "answer",
                "session_id": ready["session_id"],
                "question_id": question["id"],
                "text": "我的回答",
            }
        )
        return _recv_until(ws, "score")


def test_history_lists_recent_answered_question(tmp_path) -> None:
    with TestClient(create_app(load_settings(make_env(tmp_path)))) as client:
        score = _answer_one_question(client)
        assert score["score"] is not None

        response = client.get("/api/history/answers")
        assert response.status_code == 200
        payload = response.json()
        assert payload["hours"] == 24
        items = payload["items"]
        assert len(items) == 1
        assert items[0]["score"] == score["score"]
        assert items[0]["answer_text"] == "我的回答"
        assert items[0]["question_text"]
        assert items[0]["concept_name"]


def test_history_skips_answers_older_than_window(tmp_path) -> None:
    with TestClient(create_app(load_settings(make_env(tmp_path)))) as client:
        _answer_one_question(client)
        old = (datetime.now() - timedelta(hours=30)).isoformat(timespec="seconds")
        store = Store(connect(tmp_path / "app.db"))
        try:
            store.conn.execute("UPDATE session_questions SET created_at = ?", (old,))
            store.conn.commit()
        finally:
            store.close()

        payload = client.get("/api/history/answers?hours=24").json()
        assert payload["items"] == []

        wider = client.get("/api/history/answers?hours=48").json()
        assert len(wider["items"]) == 1
