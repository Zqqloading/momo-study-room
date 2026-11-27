from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from bff.config import load_settings
from bff.main import _question_event, _started_question_event, _unit_event, create_app
from bff.memory_extraction import MemoryExtractor
from bff.providers.base import ProviderError
from core.agent_loop import AgentTurnResult
from core.coach import SessionQuestion
from core.db import connect, init_schema
from core.persona import PersonaError, default_life_pool
from core.ports import ASRResult, SearchHit, TTSResult
from core.store import Store
from core.tts_cache import TTSCache


def make_env(tmp_path) -> dict[str, str]:
    return {
        "PROVIDER_MODE": "fake",
        "DB_PATH": str(tmp_path / "app.db"),
        "DATA_DIR": str(tmp_path / "data"),
        "CONTENT_DIR": str(tmp_path),
    }


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(load_settings(make_env(tmp_path))))


def _recv_until(ws, wanted: str, limit: int = 60) -> list[dict]:
    messages: list[dict] = []
    for _ in range(limit):
        message = ws.receive_json()
        messages.append(message)
        if message["type"] == wanted:
            return messages
    raise AssertionError(f"没有等到 {wanted}")


def _answer_text(question: dict) -> str:
    return "C" if question["kind"] == "discriminate" else "我的回答"


def _daily_life_prefix() -> str:
    life = default_life_pool().for_date(date.today().isoformat())
    return life or ""


def _life_line() -> str:
    """开场只播生活句，不再拼记忆块和选题诊断。"""
    life = _daily_life_prefix()
    return life if life.endswith(("。", "！", "？")) else f"{life}。"


def _set_states(tmp_path, updates: dict[str, dict]) -> None:
    store = Store(connect(tmp_path / "app.db"))
    try:
        for concept_id, changes in updates.items():
            state = store.concept_state(concept_id)
            assert state is not None
            store.upsert_concept(replace(state, **changes))
        store.conn.commit()
    finally:
        store.close()


def test_health_declares_fake_mode(tmp_path) -> None:
    with make_client(tmp_path) as client:
        payload = client.get("/health").json()
        assert payload["ok"] is True
        assert payload["fake"] is True
        assert payload["modes"]["llm"] == "fake"


def test_question_events_carry_type_but_not_source(tmp_path) -> None:
    started_event = _started_question_event(
        "s1",
        SessionQuestion(
            id=1,
            role="new",
            kind="recall",
            text="题",
            options=None,
            index=1,
            total=5,
            question_type="concept",
        ),
    )
    assert started_event["question_type"] == "concept"
    assert "source_url" not in started_event
    assert "source_excerpt" not in started_event

    store = Store(connect(tmp_path / "events.db"))
    init_schema(store.conn)
    try:
        question_id = store.add_question(
            session_id="s1",
            question_bank_id=None,
            concept_id="agent-loop",
            role="new",
            kind="apply",
            question_type="business",
            text="题",
            rubric_json={},
            source_url="https://example.com/m",
            source_excerpt="摘录",
            source_chunk_id="m-v1-child-001",
            generation_meta_json={"origin": "generated"},
            created_at="t",
        )
        question = store.question(question_id)
        assert question is not None
        event = _question_event(store, "s1", question)
        assert event["question_type"] == "business"
        assert event["origin"] == "generated"
        assert "source_url" not in event
        assert "source_excerpt" not in event
    finally:
        store.close()


def test_text_session_completes_and_replays(tmp_path) -> None:
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            session_id = ready["session_id"]
            question = ready["question"]
            assert ready["unit"] == {
                "kind": "daily",
                "main": {"id": "agent-loop", "name": "Agent 循环"},
                "review": None,
            }
            assert ready["intro"] == _life_line()
            assert ready["focus"] == {
                "concept_id": "agent-loop",
                "name": "Agent 循环",
                "reason_kind": "no_signal",
            }
            assert question["index"] == 1
            assert question["total"] == 5
            assert "question_type" in question
            assert question["origin"] == "fallback"
            assert "source_url" not in question

            results: dict = {}
            for turn in range(1, 6):
                ws.send_json(
                    {
                        "type": "answer",
                        "session_id": session_id,
                        "question_id": question["id"],
                        "turn_id": f"t{turn}",
                        "text": _answer_text(question),
                    }
                )
                messages = (
                    _recv_until(ws, "question")
                    if turn < 5
                    else _recv_until(ws, "session_result")
                )
                types = [message["type"] for message in messages]
                assert "score" in types
                score = next(
                    message for message in messages if message["type"] == "score"
                )
                assert "question_type" in score
                assert score["source_url"]
                assert score["source_excerpt"]
                if turn < 5:
                    question = messages[-1]
                    assert "question_type" in question
                    assert "source_url" not in question
                else:
                    results = messages[-1]

        assert results["status"] == "completed"
        # 辨析题 1 对 1 错（100 + 40），三道开放题各 70 -> 均值 70.0。
        assert results["session_score"] == 70.0
        assert len(results["scores"]) == 5
        assert all("question_type" in item for item in results["scores"])
        assert all(item["source_url"] for item in results["scores"])
        assert len(results["concepts"]) == 1
        concept = results["concepts"][0]
        assert concept["id"] == "agent-loop"
        assert concept["name"] == "Agent 循环"
        assert concept["roles"] == ["new"]
        assert concept["mastery_before"] == 0
        assert concept["mastery_after"] == 4
        assert concept["mastery_before_label"] == "未掌握"
        assert concept["mastery_after_label"] == "熟练"
        assert concept["mastery_updated"] is True
        assert concept["review_due_at"]

    conn = connect(tmp_path / "app.db")
    try:
        store = Store(conn)
        session = store.session(session_id)
        assert session is not None
        assert session["status"] == "completed"
        rows = store.session_questions(session_id)
        assert len(rows) == 5
        assert all(row["score"] is not None for row in rows)
    finally:
        conn.close()


def test_resume_returns_first_unanswered(tmp_path) -> None:
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            session_id = ready["session_id"]
            first = ready["question"]
            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": first["id"],
                    "turn_id": "t1",
                    "text": _answer_text(first),
                }
            )
            second = _recv_until(ws, "question")[-1]

        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_resume", "session_id": session_id})
            resumed = _recv_until(ws, "session_ready")[-1]
            assert resumed["session_id"] == session_id
            assert resumed["question"]["id"] == second["id"]
            assert resumed["unit"]["main"]["id"] == "agent-loop"
            assert resumed["unit"]["review"] is None
            assert "intro" not in resumed


def test_session_ready_daily_with_review_unit(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        _set_states(tmp_path, {"tool-use": {"review_due_at": "2026-11-23"}})
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            assert ready["kind"] == "daily"
            assert ready["unit"] == {
                "kind": "daily",
                "main": {"id": "agent-loop", "name": "Agent 循环"},
                "review": {"id": "tool-use", "name": "工具调用"},
            }
            assert ready["intro"] == _life_line()
            assert ready["focus"]["reason_kind"] == "no_signal"


def test_session_ready_review_only_unit(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        _set_states(
            tmp_path,
            {
                "agent-loop": {"status": "known"},
                "memory": {"status": "known"},
                "tool-use": {"review_due_at": "2026-11-23"},
            },
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            assert ready["kind"] == "review"
            assert ready["unit"]["main"] is None
            assert ready["unit"]["review"] == {
                "id": "tool-use",
                "name": "工具调用",
            }
            assert ready["intro"] == _life_line()
            assert ready["focus"] == {
                "concept_id": "tool-use",
                "name": "工具调用",
                "reason_kind": "review",
            }


def test_unit_event_falls_back_to_concept_id(tmp_path) -> None:
    store = Store(connect(tmp_path / "unit.db"))
    init_schema(store.conn)
    try:
        store.start_agent_session(
            session_id="s1",
            kind="daily",
            date="2026-11-23",
            started_at="2026-11-23T20:00:00",
        )
        store.add_question(
            session_id="s1",
            question_bank_id=None,
            concept_id="ghost",
            role="new",
            kind="apply",
            text="题",
            rubric_json={},
            source_url="fixture://ghost",
            source_excerpt="出处",
            created_at="2026-11-23T20:01:00",
        )
        event = _unit_event(store, [], "s1")
        assert event["main"] == {"id": "ghost", "name": "ghost"}
    finally:
        store.close()


def test_proposal_matches_session_ready(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        _set_states(tmp_path, {"tool-use": {"review_due_at": "2026-11-23"}})
        proposal = client.get("/api/kb/unit/proposal").json()
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            assert ready["unit"]["main"]["id"] == proposal["main"]["id"]
            assert ready["unit"]["review"]["id"] == proposal["review"]["id"]
            assert ready["unit"]["kind"] == proposal["kind"]


def test_finish_early_returns_partial(tmp_path) -> None:
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            session_id = ready["session_id"]
            question = ready["question"]
            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": question["id"],
                    "turn_id": "t1",
                    "text": _answer_text(question),
                }
            )
            _recv_until(ws, "question")

            ws.send_json({"type": "finish", "session_id": session_id})
            result = _recv_until(ws, "session_result")[-1]
            assert result["status"] == "partial"


def test_unknown_message_type_errors_but_keeps_connection(tmp_path) -> None:
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "nope"})
            error = _recv_until(ws, "error")[-1]
            assert error["stage"] == "protocol"

            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"


def test_wrong_answer_then_new_conversation_still_proposes_it(tmp_path) -> None:
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, question = _start(client, ws)
            concept_id = "agent-loop"

            for turn in range(1, 6):
                answer = "A" if question["kind"] == "discriminate" else "我的回答"
                ws.send_json(
                    {
                        "type": "answer",
                        "session_id": session_id,
                        "question_id": question["id"],
                        "turn_id": f"t{turn}",
                        "text": answer,
                    }
                )
                if turn < 5:
                    question = _recv_until(ws, "question")[-1]
                else:
                    result = _recv_until(ws, "session_result")[-1]
            assert result["status"] == "completed"

        conn = connect(tmp_path / "app.db")
        try:
            store = Store(conn)
            before = store.concept_states()
        finally:
            conn.close()

        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "conversation_new"})
            created = _recv_until(ws, "conversation_created")[-1]
            assert created["conversation_id"]

        conn = connect(tmp_path / "app.db")
        try:
            store = Store(conn)
            assert store.concept_states() == before
        finally:
            conn.close()

        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            assert ready["focus"] == {
                "concept_id": concept_id,
                "name": "Agent 循环",
                "reason_kind": "recent_miss",
            }
            assert ready["unit"]["main"]["id"] == concept_id


class _StreamingTTS:
    name = "streaming-tts"
    supports_streaming = True
    stream_mime = "audio/mpeg"

    async def synthesize(self, text: str, *, voice: str | None = None) -> TTSResult:
        return TTSResult(audio=b"whole", mime="audio/mpeg", latency_ms=1)

    async def stream(self, text: str, *, voice: str | None = None):
        yield b"part1"
        yield b"part2"


class _FailingTTS:
    name = "failing-tts"
    supports_streaming = False

    async def synthesize(self, text: str, *, voice: str | None = None) -> TTSResult:
        from bff.providers.base import ProviderError

        raise ProviderError("TTS 挂了")


def test_feedback_streams_audio_chunks_in_order(tmp_path) -> None:
    app = create_app(
        load_settings(make_env(tmp_path))
    )
    with TestClient(app) as client:
        tts = _StreamingTTS()
        app.state.providers.tts = tts
        app.state.tts_cache = TTSCache(tts, tmp_path / "cache")
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            session_id = ready["session_id"]
            question = ready["question"]
            intro_chunks = []
            while True:
                chunk = _recv_until(ws, "audio_chunk")[-1]
                if chunk["utterance"] == "question":
                    first_audio = chunk
                    break
                # 开场先播缓存短句（utterance=filler），生活句才是 intro。
                if chunk["utterance"] != "intro":
                    continue
                intro_chunks.append(chunk)
            assert intro_chunks, "开场白应该至少有音频"
            assert [chunk["seq"] for chunk in intro_chunks] == list(
                range(1, len(intro_chunks) + 1)
            )
            assert all(chunk["utterance"] == "intro" for chunk in intro_chunks)
            assert first_audio["seq"] == 1
            assert first_audio["utterance"] == "question"

            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": question["id"],
                    "turn_id": "t1",
                    "text": _answer_text(question),
                }
            )
            messages = _recv_until(ws, "feedback_end")
            assert any(message["type"] == "question" for message in messages)
            feedback_chunks = [
                message for message in messages if message["type"] == "audio_chunk"
            ]
            assert [chunk["seq"] for chunk in feedback_chunks] == [1, 2]
            assert all(chunk["mime"] == "audio/mpeg" for chunk in feedback_chunks)
            assert all(
                chunk["utterance"] == "feedback" for chunk in feedback_chunks
            )

            question_audio = _recv_until(ws, "audio_chunk")[-1]
            assert question_audio["utterance"] == "question"
            assert question_audio["seq"] == 1


def test_tts_failure_degrades_to_text_only(tmp_path) -> None:
    app = create_app(
        load_settings(make_env(tmp_path))
    )
    with TestClient(app) as client:
        failing = _FailingTTS()
        app.state.providers.tts = failing
        app.state.tts_cache = TTSCache(failing, tmp_path / "cache")
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            assert ready["intro"] == _life_line()
            first_warning = _recv_until(ws, "warning")[-1]
            assert first_warning["stage"] == "tts"
            assert "TTS 挂了" not in first_warning["message"]
            assert "语音暂时不可用" in first_warning["message"]

            session_id = ready["session_id"]
            question = ready["question"]
            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": question["id"],
                    "turn_id": "t1",
                    "text": _answer_text(question),
                }
            )
            messages = _recv_until(ws, "question")
            assert any(message["type"] == "score" for message in messages)
            assert not any(message["type"] == "audio_chunk" for message in messages)


class _ScriptedASR:
    name = "scripted-asr"

    def __init__(self, text: str) -> None:
        self.text = text

    async def transcribe(self, request) -> ASRResult:
        return ASRResult(text=self.text, confidence=None, latency_ms=1)


class _FailingASR:
    name = "failing-asr"

    async def transcribe(self, request) -> ASRResult:
        raise ProviderError("ASR 超时")


def _drain_until_question_audio(ws, limit: int = 60) -> dict:
    for _ in range(limit):
        message = ws.receive_json()
        if message["type"] == "audio_chunk" and message.get("utterance") == "question":
            return message
    raise AssertionError("没有等到题目音频")


def _start(client, ws) -> tuple[str, dict]:
    ws.send_json({"type": "session_start", "kind": "daily"})
    ready = _recv_until(ws, "session_ready")[-1]
    _drain_until_question_audio(ws)
    return ready["session_id"], ready["question"]


def _send_audio(ws, session_id: str, question_id: int, turn_id: str = "a1") -> None:
    ws.send_json(
        {
            "type": "audio",
            "session_id": session_id,
            "question_id": question_id,
            "turn_id": turn_id,
            "data": base64.b64encode(b"fake-audio").decode("ascii"),
            "sample_rate": 16000,
            "mime": "audio/wav",
        }
    )


def test_audio_one_step_submit_scores_directly(tmp_path) -> None:
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, question = _start(client, ws)
            _send_audio(ws, session_id, question["id"])

            messages = _recv_until(ws, "question")
            transcript = messages[0]
            assert transcript["type"] == "transcript"
            assert transcript["needs_confirmation"] is False
            assert any(message["type"] == "score" for message in messages)

    conn = connect(tmp_path / "app.db")
    try:
        store = Store(conn)
        agent = store.agent_session(session_id)
        assert agent is not None
        assert agent["input_mode"] == "voice"
    finally:
        conn.close()


def test_suspicious_transcript_pauses(tmp_path) -> None:
    app = create_app(
        load_settings(make_env(tmp_path))
    )
    with TestClient(app) as client:
        app.state.providers.asr = _ScriptedASR("嗯")
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, question = _start(client, ws)
            _send_audio(ws, session_id, question["id"])

            transcript = _recv_until(ws, "transcript")[-1]
            assert transcript["needs_confirmation"] is True
            assert transcript["reason"] == "suspicious"


def test_mixed_transcript_pauses(tmp_path) -> None:
    app = create_app(
        load_settings(make_env(tmp_path))
    )
    with TestClient(app) as client:
        app.state.providers.asr = _ScriptedASR("agent 循环是什么？")
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, question = _start(client, ws)
            _send_audio(ws, session_id, question["id"])

            transcript = _recv_until(ws, "transcript")[-1]
            assert transcript["needs_confirmation"] is True
            assert transcript["reason"] == "mixed"


def test_whitelist_transcript_is_not_suspicious(tmp_path) -> None:
    app = create_app(
        load_settings(make_env(tmp_path))
    )
    with TestClient(app) as client:
        app.state.providers.asr = _ScriptedASR("不知道")
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, question = _start(client, ws)
            _send_audio(ws, session_id, question["id"])

            messages = _recv_until(ws, "question")
            transcript = messages[0]
            assert transcript["type"] == "transcript"
            assert transcript["needs_confirmation"] is False
            score = next(message for message in messages if message["type"] == "score")
            assert score["score"] == 0


def test_asr_failure_sets_text_mode_and_keeps_session(tmp_path) -> None:
    app = create_app(
        load_settings(make_env(tmp_path))
    )
    with TestClient(app) as client:
        app.state.providers.asr = _FailingASR()
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, question = _start(client, ws)
            _send_audio(ws, session_id, question["id"])

            error = _recv_until(ws, "error")[-1]
            assert error["stage"] == "asr"
            assert "文字" in error["message"]

    conn = connect(tmp_path / "app.db")
    try:
        store = Store(conn)
        agent = store.agent_session(session_id)
        assert agent is not None
        assert agent["input_mode"] == "text"
        assert agent["status"] == "active"
    finally:
        conn.close()


def test_empty_asr_text_pauses_as_suspicious(tmp_path) -> None:
    app = create_app(
        load_settings(make_env(tmp_path))
    )
    with TestClient(app) as client:
        app.state.providers.asr = _ScriptedASR("")
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, question = _start(client, ws)
            _send_audio(ws, session_id, question["id"])

            transcript = _recv_until(ws, "transcript")[-1]
            assert transcript["text"] == ""
            assert transcript["needs_confirmation"] is True
            assert transcript["reason"] == "suspicious"


def test_free_talk_teach_mode_without_session(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        app.state.providers.asr = _ScriptedASR("什么是 agent 循环")
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {
                    "type": "audio",
                    "turn_id": "f1",
                    "data": base64.b64encode(b"free-talk").decode("ascii"),
                    "sample_rate": 16000,
                    "mime": "audio/wav",
                }
            )
            messages = _recv_until(ws, "reply")
            transcript = next(
                message for message in messages if message["type"] == "transcript"
            )
            assert transcript["needs_confirmation"] is False
            reply = messages[-1]
            assert reply["mode"] == "teach"
            assert reply["text"]
            chunk = _recv_until(ws, "audio_chunk")[-1]
            assert chunk["seq"] == 1

    conn = connect(tmp_path / "app.db")
    try:
        store = Store(conn)
        assert store.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        conversation = store.latest_conversation()
        assert conversation is not None
        messages = store.conversation_messages(conversation["id"])
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert messages[0]["text"] == "什么是 agent 循环"
        assert messages[1]["text"] == reply["text"]
        assert conversation["title"] == "什么是 agent 循环"
    finally:
        conn.close()


def test_conversation_new_list_and_load(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        app.state.providers.asr = _ScriptedASR("今天好累")
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "conversation_new"})
            created = _recv_until(ws, "conversation_created")[-1]
            conversation_id = created["conversation_id"]

            ws.send_json({"type": "conversation_list"})
            items = _recv_until(ws, "conversation_list")[-1]["items"]
            assert any(
                item["conversation_id"] == conversation_id for item in items
            )

            ws.send_json(
                {
                    "type": "audio",
                    "conversation_id": conversation_id,
                    "turn_id": "c1",
                    "data": base64.b64encode(b"free-talk").decode("ascii"),
                    "sample_rate": 16000,
                    "mime": "audio/wav",
                }
            )
            reply = _recv_until(ws, "reply")[-1]
            assert reply["conversation_id"] == conversation_id

            ws.send_json(
                {
                    "type": "conversation_load",
                    "conversation_id": conversation_id,
                }
            )
            loaded = _recv_until(ws, "conversation_loaded")[-1]
            assert loaded["conversation_id"] == conversation_id
            assert [message["role"] for message in loaded["messages"]] == [
                "user",
                "assistant",
            ]


def test_conversation_rename_and_delete(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "conversation_new"})
            conversation_id = _recv_until(ws, "conversation_created")[-1][
                "conversation_id"
            ]

            ws.send_json(
                {
                    "type": "conversation_rename",
                    "conversation_id": conversation_id,
                    "title": "  我的新对话  ",
                }
            )
            renamed = _recv_until(ws, "conversation_renamed")[-1]
            assert renamed["conversation_id"] == conversation_id
            assert renamed["title"] == "我的新对话"

            ws.send_json({"type": "conversation_list"})
            items = _recv_until(ws, "conversation_list")[-1]["items"]
            assert items[0]["title"] == "我的新对话"

            ws.send_json({"type": "conversation_rename", "conversation_id": conversation_id, "title": "   "})
            assert _recv_until(ws, "error")[-1]["stage"] == "protocol"

            ws.send_json(
                {"type": "conversation_delete", "conversation_id": conversation_id}
            )
            deleted = _recv_until(ws, "conversation_deleted")[-1]
            assert deleted["conversation_id"] == conversation_id

            ws.send_json({"type": "conversation_list"})
            assert _recv_until(ws, "conversation_list")[-1]["items"] == []


def test_free_talk_chat_mode_without_session(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        app.state.providers.asr = _ScriptedASR("今天好累")
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {
                    "type": "audio",
                    "turn_id": "f2",
                    "data": base64.b64encode(b"free-talk").decode("ascii"),
                    "sample_rate": 16000,
                    "mime": "audio/wav",
                }
            )
            reply = _recv_until(ws, "reply")[-1]
            assert reply["mode"] == "chat"


def test_free_talk_mode_switch_overrides_classifier(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        app.state.providers.asr = _ScriptedASR("你叫什么名字")
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {
                    "type": "audio",
                    "turn_id": "f3",
                    "data": base64.b64encode(b"free-talk").decode("ascii"),
                    "sample_rate": 16000,
                    "mime": "audio/wav",
                    "mode": "chat",
                }
            )
            assert _recv_until(ws, "reply")[-1]["mode"] == "chat"

            ws.send_json(
                {
                    "type": "text",
                    "turn_id": "f4",
                    "text": "今天好累",
                    "mode": "teach",
                }
            )
            assert _recv_until(ws, "reply")[-1]["mode"] == "teach"


def test_skip_advances_to_next_question(tmp_path) -> None:
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, first = _start(client, ws)

            ws.send_json(
                {
                    "type": "skip",
                    "session_id": session_id,
                    "question_id": first["id"],
                    "turn_id": "s1",
                }
            )
            second = _recv_until(ws, "question")[-1]
            assert second["id"] != first["id"]
            assert second["index"] == 2

    conn = connect(tmp_path / "app.db")
    try:
        store = Store(conn)
        row = store.question(first["id"])
        assert row is not None
        assert row["score"] is None
        assert row["answer_text"] is None
    finally:
        conn.close()


def _skip(ws, session_id: str, question_id: int, turn_id: str) -> None:
    ws.send_json(
        {
            "type": "skip",
            "session_id": session_id,
            "question_id": question_id,
            "turn_id": turn_id,
        }
    )


def test_choice_feedback_only_speaks_when_wrong(tmp_path) -> None:
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, first = _start(client, ws)
            question = first
            for index in range(5):
                if question["kind"] == "discriminate":
                    break
                _skip(ws, session_id, question["id"], f"s{index}")
                question = _recv_until(ws, "question")[-1]
            else:
                raise AssertionError("本场没有辨析题")
            third = question
            assert third["kind"] == "discriminate"

            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": third["id"],
                    "turn_id": "a1",
                    "text": "C",
                }
            )
            messages = _recv_until(ws, "feedback_end")
            spoken = [
                message
                for message in messages
                if message["type"] == "audio_chunk"
                and message.get("utterance") == "feedback"
            ]
            assert spoken == []
            score = next(message for message in messages if message["type"] == "score")
            assert score["why"] == "答对了"

            fourth = next(
                message for message in messages if message["type"] == "question"
            )
            assert fourth["kind"] == "discriminate"
            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": fourth["id"],
                    "turn_id": "a2",
                    "text": "A",
                }
            )
            wrong_messages = _recv_until(ws, "feedback_end")
            wrong_spoken = [
                message
                for message in wrong_messages
                if message["type"] == "audio_chunk"
                and message.get("utterance") == "feedback"
            ]
            assert wrong_spoken
            wrong_score = next(
                message for message in wrong_messages if message["type"] == "score"
            )
            assert "解析" in wrong_score["why"]
            assert "再次观察" in wrong_score["why"]


def _seed_material(db_path, text: str = "模型自作主张会加需求。") -> None:
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
                    "text": text,
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


def test_text_free_talk_returns_material_sources(tmp_path) -> None:
    _seed_material(tmp_path / "app.db")
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {"type": "text", "text": "什么是 模型自作主张", "turn_id": "t1"}
            )
            reply = _recv_until(ws, "reply")[-1]
            assert reply["mode"] == "teach"
            assert reply["sources"]
            assert reply["sources"][0]["index"] == 1
            assert reply["sources"][0]["title"] == "note"
            assert "自作主张" in reply["sources"][0]["excerpt"]

            ws.send_json(
                {
                    "type": "conversation_load",
                    "conversation_id": reply["conversation_id"],
                }
            )
            loaded = _recv_until(ws, "conversation_loaded")[-1]
            assistant = [
                message
                for message in loaded["messages"]
                if message["role"] == "assistant"
            ][-1]
            assert assistant["sources"] == reply["sources"]


def test_text_free_talk_without_material_hit_has_no_sources(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {"type": "text", "text": "什么是 不存在的概念", "turn_id": "t1"}
            )
            reply = _recv_until(ws, "reply")[-1]
            assert reply["sources"] == []
            assert reply["grounded"] is False
            assert reply["text"].startswith("材料里没有直接讲到")


def _web_hit(
    content: str,
    *,
    title: str = "网页结果",
    url: str = "https://example.com/a",
    published_at: str | None = "2026-11-20",
) -> SearchHit:
    return SearchHit(
        title=title,
        url=url,
        content=content,
        score=0.9,
        published_at=published_at,
    )


class _ScriptedSearch:
    name = "scripted-search"

    def __init__(
        self, hits: list[SearchHit] | None = None, error: Exception | None = None
    ) -> None:
        self.hits = list(hits or [])
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        self.calls.append((query, max_results))
        if self.error is not None:
            raise self.error
        return list(self.hits[:max_results])


class _EmptySearch:
    name = "empty-search"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        return []


class _SlowSearch:
    name = "slow-search"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        await asyncio.sleep(0.2)
        return []


def test_local_hit_skips_web_search(tmp_path) -> None:
    _seed_material(tmp_path / "app.db")
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        search = _ScriptedSearch([_web_hit("模型自作主张 " + "正文" * 50)])
        app.state.providers.search = search
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {"type": "text", "text": "什么是 模型自作主张", "turn_id": "t1"}
            )
            reply = _recv_until(ws, "reply")[-1]
            assert search.calls == []
            assert reply["web_status"] == "off"
            assert [source["kind"] for source in reply["sources"]] == ["material"]


def test_explicit_web_request_searches_even_with_local_hit(tmp_path) -> None:
    _seed_material(tmp_path / "app.db")
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        search = _ScriptedSearch(
            [_web_hit("模型自作主张 最新说明 " + "正文" * 50)]
        )
        app.state.providers.search = search
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {"type": "text", "text": "联网查一下 模型自作主张", "turn_id": "t1"}
            )
            reply = _recv_until(ws, "reply")[-1]
            assert search.calls
            assert reply["web_status"] == "ok"
            kinds = [source["kind"] for source in reply["sources"]]
            assert kinds == ["material", "web"]


def test_time_question_without_local_hit_uses_web(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        search = _ScriptedSearch(
            [
                _web_hit(
                    "agent 最新版本 " + "正文" * 50,
                    url="https://www.example.com/agent",
                )
            ]
        )
        app.state.providers.search = search
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {"type": "text", "text": "最新的 agent 版本", "turn_id": "t1"}
            )
            reply = _recv_until(ws, "reply")[-1]
            assert search.calls
            assert reply["web_status"] == "ok"
            assert reply["sources"][0]["kind"] == "web"
            assert reply["sources"][0]["domain"] == "example.com"
            assert reply["sources"][0]["published_at"] == "2026-11-20"
            assert reply["sources"][0]["retrieved_at"]


def test_search_failure_falls_back_with_warning(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        app.state.providers.search = _ScriptedSearch(error=ProviderError("搜索挂了"))
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {"type": "text", "text": "最新的 agent 版本", "turn_id": "t1"}
            )
            messages = _recv_until(ws, "reply")
            assert any(
                message.get("type") == "warning"
                and message.get("stage") == "search"
                for message in messages
            )
            reply = messages[-1]
            assert reply["web_status"] == "failed"
            assert reply["sources"] == []
            assert reply["text"].startswith("材料里没有直接讲到，联网搜索暂时不可用")


def test_search_empty_falls_back_with_distinct_copy(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        app.state.providers.search = _EmptySearch()
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {"type": "text", "text": "最新的 agent 版本", "turn_id": "t1"}
            )
            reply = _recv_until(ws, "reply")[-1]
            assert reply["web_status"] == "empty"
            assert reply["text"].startswith("材料里没有直接讲到，联网也没查到")


def test_search_timeout_falls_back_with_warning(tmp_path) -> None:
    env = make_env(tmp_path)
    env["SEARCH_TIMEOUT_SECONDS"] = "0.05"
    app = create_app(load_settings(env))
    with TestClient(app) as client:
        app.state.providers.search = _SlowSearch()
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {"type": "text", "text": "最新的 agent 版本", "turn_id": "t1"}
            )
            messages = _recv_until(ws, "reply")
            assert any(
                message.get("type") == "warning"
                and message.get("stage") == "search"
                for message in messages
            )
            reply = messages[-1]
            assert reply["web_status"] == "failed"


def test_web_sources_persist_and_load(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        app.state.providers.search = _ScriptedSearch(
            [_web_hit("agent 最新版本 " + "正文" * 50)]
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {"type": "text", "text": "最新的 agent 版本", "turn_id": "t1"}
            )
            reply = _recv_until(ws, "reply")[-1]
            assert reply["sources"][0]["kind"] == "web"

            ws.send_json(
                {
                    "type": "conversation_load",
                    "conversation_id": reply["conversation_id"],
                }
            )
            loaded = _recv_until(ws, "conversation_loaded")[-1]
            assistant = [
                message
                for message in loaded["messages"]
                if message["role"] == "assistant"
            ][-1]
            assert assistant["sources"] == reply["sources"]


def test_health_reports_search_real_with_key(tmp_path) -> None:
    env = make_env(tmp_path)
    env["PROVIDER_MODE"] = "auto"
    env["TAVILY_API_KEY"] = "tvly-test"
    app = create_app(load_settings(env))
    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["modes"]["search"] == "real"


def test_session_ready_intro_includes_daily_life_sentence(tmp_path) -> None:
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start"})
            ready = _recv_until(ws, "session_ready")[-1]
            expected = default_life_pool().for_date(date.today().isoformat())
            assert expected
            assert ready["intro"].startswith(expected)


def test_custom_persona_life_sentence_is_used(tmp_path) -> None:
    (tmp_path / "persona.yaml").write_text(
        "version: 1\n"
        "life_pool:\n"
        "  enabled: true\n"
        "  items:\n"
        "  - id: only\n"
        "    text: 今天只做了一件很小的事\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start"})
            ready = _recv_until(ws, "session_ready")[-1]
            assert ready["intro"].startswith("今天只做了一件很小的事。")
            assert "。 今天" not in ready["intro"]


def test_broken_persona_fails_startup(tmp_path) -> None:
    (tmp_path / "persona.yaml").write_text("version: 2\n", encoding="utf-8")
    with pytest.raises(PersonaError):
        with make_client(tmp_path) as client:
            client.get("/health")


def test_session_resume_does_not_repeat_intro(tmp_path) -> None:
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start"})
            ready = _recv_until(ws, "session_ready")[-1]
            ws.send_json(
                {"type": "session_resume", "session_id": ready["session_id"]}
            )
            resumed = _recv_until(ws, "session_ready")[-1]
            assert "intro" not in resumed


MIDPOINT_EMOTION = {"comfort": 0.0, "energy": 0.5, "tone": "语气平稳自然。"}


class _EmotionScorer:
    name = "scripted-emotion"

    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        return self.payload


def test_ready_and_session_ready_carry_midpoint_emotion(tmp_path) -> None:
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            assert ready["emotion"] == MIDPOINT_EMOTION

            ws.send_json({"type": "session_start"})
            started = _recv_until(ws, "session_ready")[-1]
            assert started["emotion"] == MIDPOINT_EMOTION


def test_free_talk_sends_emotion_before_reply(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        from bff.emotion import EmotionUpdater

        app.state.emotion = EmotionUpdater(
            app.state.store,
            _EmotionScorer(
                '{"comfort_delta":0.2,"energy_delta":-0.1,"intense":false}'
            ),
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "text", "text": "今天有点累", "turn_id": "t1"})
            messages = _recv_until(ws, "reply")
            types = [message["type"] for message in messages]
            assert types.index("emotion") < types.index("reply")
            emotion = next(
                message for message in messages if message["type"] == "emotion"
            )
            assert emotion["comfort"] == 0.2
            assert emotion["energy"] == 0.4
            assert emotion["tone"] == "语气平稳自然。"


def test_answer_turn_does_not_send_emotion(tmp_path) -> None:
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, question = _start(client, ws)
            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": question["id"],
                    "turn_id": "t1",
                    "text": _answer_text(question),
                }
            )
            messages = _recv_until(ws, "question")
            assert not any(message["type"] == "emotion" for message in messages)


def test_emotion_disabled_skips_event_and_keeps_midpoint(tmp_path) -> None:
    env = make_env(tmp_path)
    env["EMOTION_ENABLED"] = "off"
    app = create_app(load_settings(env))
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ready = ws.receive_json()
            assert ready["emotion"] == MIDPOINT_EMOTION
            ws.send_json({"type": "text", "text": "今天有点累", "turn_id": "t1"})
            messages = _recv_until(ws, "reply")
            assert not any(message["type"] == "emotion" for message in messages)


def test_teach_sends_emotion_before_teach_reply(tmp_path) -> None:
    env = make_env(tmp_path)
    env["AGENT_HARNESS"] = "on"
    app = create_app(load_settings(env))
    with TestClient(app) as client:
        from bff.emotion import EmotionUpdater

        app.state.emotion = EmotionUpdater(
            app.state.store,
            _EmotionScorer(
                '{"comfort_delta":0.2,"energy_delta":0.2,"intense":false}'
            ),
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, question = _start(client, ws)
            ws.send_json(
                {
                    "type": "text",
                    "session_id": session_id,
                    "question_id": question["id"],
                    "text": "这题什么意思",
                    "intent": "clarify",
                    "turn_id": "q1",
                }
            )
            messages = _recv_until(ws, "teach_reply")
            types = [message["type"] for message in messages]
            assert types.index("emotion") < types.index("teach_reply")
            emotion = next(
                message for message in messages if message["type"] == "emotion"
            )
            assert (emotion["comfort"], emotion["energy"]) == (0.2, 0.7)


def _seed_memory(
    db_path,
    *,
    kind: str = "quote",
    text: str = "怕公式",
    source_quote: str = "我有点怕公式",
    strength: float = 1.0,
) -> None:
    store = Store(connect(db_path))
    try:
        init_schema(store.conn)
        store.add_user_memory(
            user_id="owner",
            kind=kind,
            text=text,
            source_quote=source_quote,
            source_session_id="seed",
            source_question_id=None,
            strength=strength,
            half_life_days=14.0,
            last_recalled_at="2026-11-26T09:00:00",
            created_at="2026-11-26T09:00:00",
        )
    finally:
        store.close()


def _read_memory_run(db_path, session_id: str) -> dict | None:
    store = Store(connect(db_path))
    try:
        return store.memory_run_for_session("owner", session_id)
    finally:
        store.close()


def _wait_memory_run(db_path, session_id: str) -> dict | None:
    for _ in range(100):
        row = _read_memory_run(db_path, session_id)
        if row is not None and row["status"] != "running":
            return row
        time.sleep(0.05)
    return _read_memory_run(db_path, session_id)


def test_session_ready_sends_lecture_instead_of_memory_block(tmp_path) -> None:
    """开场不再复述记忆/诊断：只播生活句，讲解单独走 lecture 事件。"""
    _seed_memory(tmp_path / "app.db")
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start"})
            ready = _recv_until(ws, "session_ready")[-1]
            assert ready["intro"] == _life_line()
            assert "先想起几件你说过的事：" not in ready["intro"]
            lecture = _recv_until(ws, "lecture")[-1]
            assert lecture["text"].strip()
            assert lecture["session_id"] == ready["session_id"]


def test_memory_disabled_skips_opening_block(tmp_path) -> None:
    env = make_env(tmp_path)
    env["MEMORY_ENABLED"] = "off"
    _seed_memory(tmp_path / "app.db")
    app = create_app(load_settings(env))
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start"})
            ready = _recv_until(ws, "session_ready")[-1]
            assert "先想起几件你说过的事：" not in ready["intro"]


class _RecordingLLM:
    name = "recording-llm"

    def __init__(self) -> None:
        self.calls: list[list] = []

    async def complete(self, messages, **kwargs) -> str:
        self.calls.append(list(messages))
        return "我记得你怕公式。"


def test_free_talk_injects_recalled_memory(tmp_path) -> None:
    _seed_memory(tmp_path / "app.db")
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        recorder = _RecordingLLM()
        app.state.providers.chat = recorder
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {
                    "type": "text",
                    "text": "你还记得我之前说怕公式吗",
                    "turn_id": "m1",
                }
            )
            _recv_until(ws, "reply")
        system = recorder.calls[0][0].content
        assert "【用户要求回忆】" in system
        assert "- 怕公式" in system


def test_free_talk_recall_without_hit_says_no_memory(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        recorder = _RecordingLLM()
        app.state.providers.chat = recorder
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {
                    "type": "text",
                    "text": "你还记得我之前说怕公式吗",
                    "turn_id": "m1",
                }
            )
            _recv_until(ws, "reply")
        system = recorder.calls[0][0].content
        assert "【用户要求回忆】" in system
        assert "（没有找到相关记忆）" in system


class _RecordingAgentLoop:
    def __init__(self) -> None:
        self.briefs: list = []

    async def run(self, brief, text, *, on_status=None) -> AgentTurnResult:
        self.briefs.append(brief)
        return AgentTurnResult(content="好")


def test_agent_free_talk_brief_carries_memory_context(tmp_path) -> None:
    _seed_memory(tmp_path / "app.db")
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        loop = _RecordingAgentLoop()
        app.state.agent_loop = loop
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {
                    "type": "text",
                    "text": "你还记得我之前说怕公式吗",
                    "turn_id": "m1",
                }
            )
            _recv_until(ws, "reply")
        assert loop.briefs[0].memory_context == "- 怕公式"


class _MemoryScorer:
    name = "memory-scorer"

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        return (
            '{"memories":[{"kind":"quote","text":"习惯直接作答",'
            '"source_quote":"我的回答"}]}'
        )


def _read_memories(db_path) -> list[dict]:
    store = Store(connect(db_path))
    try:
        return store.user_memories("owner")
    finally:
        store.close()


def test_finish_schedules_memory_extraction(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        app.state.memory_extractor = MemoryExtractor(
            app.state.store, _MemoryScorer(), user_id="owner"
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, question = _start(client, ws)
            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": question["id"],
                    "turn_id": "t1",
                    "text": "我的回答",
                }
            )
            _recv_until(ws, "question")
            ws.send_json({"type": "finish", "session_id": session_id})
            result = _recv_until(ws, "session_result")[-1]
            assert result["status"] == "partial"

        run = _wait_memory_run(tmp_path / "app.db", session_id)
        assert run is not None
        assert run["status"] == "succeeded"
        assert run["memory_count"] == 1


def test_last_answer_schedules_memory_extraction(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        app.state.memory_extractor = MemoryExtractor(
            app.state.store, _MemoryScorer(), user_id="owner"
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            session_id, question = _start(client, ws)
            for turn in range(1, 6):
                ws.send_json(
                    {
                        "type": "answer",
                        "session_id": session_id,
                        "question_id": question["id"],
                        "turn_id": f"t{turn}",
                        "text": "我的回答",
                    }
                )
                messages = (
                    _recv_until(ws, "question")
                    if turn < 5
                    else _recv_until(ws, "session_result")
                )
                if turn < 5:
                    question = messages[-1]
            assert messages[-1]["status"] == "completed"

        run = _wait_memory_run(tmp_path / "app.db", session_id)
        assert run is not None
        assert run["status"] == "succeeded"
        assert run["memory_count"] == 1


def test_memory_disabled_skips_recall_and_extraction(tmp_path) -> None:
    env = make_env(tmp_path)
    env["MEMORY_ENABLED"] = "off"
    app = create_app(load_settings(env))
    with TestClient(app) as client:
        recorder = _RecordingLLM()
        app.state.providers.chat = recorder
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {
                    "type": "text",
                    "text": "你还记得我之前说怕公式吗",
                    "turn_id": "m1",
                }
            )
            _recv_until(ws, "reply")
            session_id, question = _start(client, ws)
            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": question["id"],
                    "turn_id": "t1",
                    "text": "我的回答",
                }
            )
            _recv_until(ws, "question")
            ws.send_json({"type": "finish", "session_id": session_id})
            _recv_until(ws, "session_result")
        system = recorder.calls[0][0].content
        assert "【用户要求回忆】" not in system
        time.sleep(0.2)
        assert _read_memory_run(tmp_path / "app.db", session_id) is None
        assert _read_memories(tmp_path / "app.db") == []
