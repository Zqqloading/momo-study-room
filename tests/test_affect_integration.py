from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from bff.config import load_settings
from bff.emotion import EmotionUpdater
from bff.main import create_app
from bff.memory_extraction import MemoryExtractor
from core.db import connect
from core.store import Store

ANSWER = "我更喜欢先看例子，再看定义"


class _EmotionScorer:
    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        return '{"comfort_delta":0.2,"energy_delta":-0.1,"intense":false}'


class _MemoryScorer:
    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        return (
            '{"memories":[{"kind":"preference","text":"更习惯先看例子",'
            '"source_quote":"更喜欢先看例子"}]}'
        )


def _env(tmp_path) -> dict[str, str]:
    return {
        "PROVIDER_MODE": "fake",
        "DB_PATH": str(tmp_path / "app.db"),
        "DATA_DIR": str(tmp_path / "data"),
        "CONTENT_DIR": str(tmp_path),
        "TTS_KIND": "fake",
    }


def _recv_until(ws, wanted: str, limit: int = 160) -> list[dict]:
    messages: list[dict] = []
    for _ in range(limit):
        message = ws.receive_json()
        messages.append(message)
        if message["type"] == wanted:
            return messages
    raise AssertionError(f"没有等到 {wanted}")


def _read_run(db_path, session_id: str) -> dict | None:
    store = Store(connect(db_path))
    try:
        return store.memory_run_for_session("owner", session_id)
    finally:
        store.close()


def _wait_run(db_path, session_id: str) -> dict | None:
    for _ in range(100):
        row = _read_run(db_path, session_id)
        if row is not None and row["status"] != "running":
            return row
        time.sleep(0.05)
    return _read_run(db_path, session_id)


def _answer_all(ws, session_id: str, first_question: dict) -> dict:
    question = first_question
    result: dict = {}
    for turn in range(1, 6):
        ws.send_json(
            {
                "type": "answer",
                "session_id": session_id,
                "question_id": question["id"],
                "turn_id": f"t{turn}",
                "text": ANSWER,
            }
        )
        messages = (
            _recv_until(ws, "question")
            if turn < 5
            else _recv_until(ws, "session_result")
        )
        if turn < 5:
            question = messages[-1]
        else:
            result = messages[-1]
    return result


def test_unit_end_extracts_memory_and_next_opening_uses_it(tmp_path) -> None:
    app = create_app(load_settings(_env(tmp_path)))
    with TestClient(app) as client:
        app.state.emotion = EmotionUpdater(
            app.state.store, _EmotionScorer(), user_id="owner"
        )
        app.state.memory_extractor = MemoryExtractor(
            app.state.store, _MemoryScorer(), user_id="owner"
        )

        with client.websocket_connect("/ws") as ws:
            ready = ws.receive_json()
            assert ready["emotion"]["comfort"] == 0.0

            ws.send_json(
                {"type": "text", "text": "今天有点累", "turn_id": "f1"}
            )
            messages = _recv_until(ws, "reply")
            emotion = next(
                message for message in messages if message["type"] == "emotion"
            )
            assert (emotion["comfort"], emotion["energy"]) == (0.2, 0.4)

            ws.send_json({"type": "session_start", "kind": "daily"})
            started = _recv_until(ws, "session_ready")[-1]
            assert "先想起几件你说过的事：" not in started["intro"]
            assert started["emotion"]["comfort"] == pytest.approx(0.2, abs=0.01)

            result = _answer_all(ws, started["session_id"], started["question"])
            assert result["status"] == "completed"

        run = _wait_run(tmp_path / "app.db", started["session_id"])
        assert run is not None
        assert run["status"] == "succeeded"
        assert run["memory_count"] == 1

        with client.websocket_connect("/ws") as ws:
            ready = ws.receive_json()
            assert ready["emotion"]["comfort"] == pytest.approx(0.2, abs=0.01)
            assert ready["emotion"]["energy"] == pytest.approx(0.4, abs=0.01)

            ws.send_json({"type": "session_start", "kind": "daily"})
            second = _recv_until(ws, "session_ready")[-1]
            # 单元开场改讲知识点，不再复述记忆；记忆仍留在库里供自由对话召回。
            assert "先想起几件你说过的事：" not in second["intro"]
            assert second["emotion"]["comfort"] == pytest.approx(0.2, abs=0.01)
