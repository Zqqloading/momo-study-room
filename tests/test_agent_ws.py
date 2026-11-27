from __future__ import annotations

from fastapi.testclient import TestClient

from bff.agent_tools import SearchWebTool
from bff.config import load_settings
from bff.main import create_app
from bff.providers.fake import FakeSearch
from core.agent_loop import AgentLoop
from core.agent_tools import DEFAULT_TOOL_SPECS, ToolRegistry, ToolResult
from core.db import connect
from core.ports import AgentResponse, AgentToolCall
from core.store import Store


class ScriptedAgentClient:
    name = "scripted-agent"

    def __init__(self, script) -> None:
        self.script = list(script)
        self.calls: list[dict] = []

    async def complete(
        self,
        messages,
        *,
        tools=(),
        tool_choice="auto",
        timeout_seconds=15.0,
    ):
        self.calls.append(
            {
                "messages": tuple(messages),
                "tools": tuple(tools),
                "tool_choice": tool_choice,
            }
        )
        if not self.script:
            return AgentResponse(content="完成")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _env(tmp_path, *, agent: bool) -> dict[str, str]:
    return {
        "PROVIDER_MODE": "fake",
        "DB_PATH": str(tmp_path / "app.db"),
        "DATA_DIR": str(tmp_path / "data"),
        "CONTENT_DIR": str(tmp_path),
        "AGENT_HARNESS": "on" if agent else "off",
    }


def _client(tmp_path, *, agent: bool) -> TestClient:
    return TestClient(create_app(load_settings(_env(tmp_path, agent=agent))))


def _recv_until(ws, wanted: str, limit: int = 80) -> list[dict]:
    messages: list[dict] = []
    for _ in range(limit):
        message = ws.receive_json()
        messages.append(message)
        if message["type"] == wanted:
            return messages
    raise AssertionError(f"没有等到 {wanted}")


def _start(ws) -> dict:
    assert ws.receive_json()["type"] == "ready"
    ws.send_json({"type": "session_start", "kind": "daily"})
    return _recv_until(ws, "session_ready")[-1]


async def _material_handler(arguments):
    return ToolResult.success(
        "search_materials",
        {
            "sources": [
                {
                    "chunk_id": "chunk-1",
                    "title": "材料",
                    "url": "fixture://1",
                    "excerpt": "摘录",
                }
            ]
        },
    )


def _loop(script) -> AgentLoop:
    registry = ToolRegistry(
        DEFAULT_TOOL_SPECS,
        {"search_materials": _material_handler, "search_web": _material_handler},
    )
    return AgentLoop(ScriptedAgentClient(script), registry)


def test_free_talk_uses_agent_reply_with_sources(tmp_path) -> None:
    with _client(tmp_path, agent=True) as client:
        client.app.state.agent_loop = _loop(
            [
                AgentResponse(
                    content="",
                    tool_calls=(
                        AgentToolCall(
                            id="call-1",
                            name="search_materials",
                            arguments='{"query": "agent"}',
                        ),
                    ),
                ),
                AgentResponse(content="最终回答"),
            ]
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "text", "text": "查一下 agent"})
            messages = _recv_until(ws, "reply")
            reply = messages[-1]
            assert reply["text"] == "最终回答"
            assert reply["mode"] == "teach"
            assert reply["sources"][0]["chunk_id"] == "chunk-1"
            assert reply["agent"]["tool_calls"] == 1
            assert any(
                item["type"] == "agent_status" and item["phase"] == "searching"
                for item in messages
            )


def test_free_talk_without_sources_gets_general_knowledge_prefix(tmp_path) -> None:
    with _client(tmp_path, agent=True) as client:
        client.app.state.agent_loop = _loop(
            [AgentResponse(content="直接回答")]
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "text", "text": "嗨"})
            reply = _recv_until(ws, "reply")[-1]
            assert reply["text"].startswith("材料里没有直接讲到，以下是一般知识：")
            assert reply["mode"] == "chat"
            assert reply["sources"] == []
            assert "sessions" not in reply


def test_teach_turn_does_not_score_or_advance(tmp_path) -> None:
    with _client(tmp_path, agent=True) as client:
        client.app.state.agent_loop = _loop([AgentResponse(content="讲解内容")])
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            session_id = ready["session_id"]
            question_id = ready["question"]["id"]

            ws.send_json(
                {
                    "type": "text",
                    "session_id": session_id,
                    "question_id": question_id,
                    "intent": "teach",
                    "text": "讲讲这题",
                }
            )
            teach = _recv_until(ws, "teach_reply")[-1]
            assert teach["mode"] == "teach"
            assert teach["text"].endswith("讲解内容")
            assert teach["question_id"] == question_id

        store = Store(connect(tmp_path / "app.db"))
        try:
            rows = store.session_questions(session_id)
            assert len(rows) == 5
            assert all(row["score"] is None for row in rows)
            assert all(row["answer_text"] is None for row in rows)
            agent_session = store.agent_session(session_id)
            assert agent_session is not None
            assert agent_session["status"] == "active"
        finally:
            store.close()


def test_repeat_resends_current_question_without_scoring(tmp_path) -> None:
    with _client(tmp_path, agent=False) as client:
        with client.websocket_connect("/ws") as ws:
            ready = _start(ws)
            session_id = ready["session_id"]
            question_id = ready["question"]["id"]

            ws.send_json(
                {
                    "type": "repeat",
                    "session_id": session_id,
                    "question_id": question_id,
                }
            )
            first = _recv_until(ws, "question")
            assert first[-1]["id"] == question_id
            assert all(message["type"] != "score" for message in first)

            ws.send_json(
                {
                    "type": "text",
                    "session_id": session_id,
                    "question_id": question_id,
                    "text": "再读一遍",
                }
            )
            second = _recv_until(ws, "question")
            assert second[-1]["id"] == question_id
            assert all(message["type"] != "score" for message in second)

        store = Store(connect(tmp_path / "app.db"))
        try:
            rows = store.session_questions(session_id)
            assert all(row["score"] is None for row in rows)
            assert all(row["answer_text"] is None for row in rows)
        finally:
            store.close()


def test_duplicate_answer_replays_without_overwrite(tmp_path) -> None:
    with _client(tmp_path, agent=False) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            session_id = ready["session_id"]
            question_id = ready["question"]["id"]

            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": question_id,
                    "text": "第一次回答",
                }
            )
            first = _recv_until(ws, "score")[-1]
            assert first["duplicate"] is False

            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": question_id,
                    "text": "第二次回答",
                }
            )
            second = _recv_until(ws, "score")[-1]
            assert second["duplicate"] is True
            assert second["score"] == first["score"]

        store = Store(connect(tmp_path / "app.db"))
        try:
            rows = store.session_questions(session_id)
            assert len(rows) == 5
            answered = [row for row in rows if row["score"] is not None]
            assert len(answered) == 1
            assert answered[0]["answer_text"] == "第一次回答"
        finally:
            store.close()


def test_retry_answer_overwrites_same_row(tmp_path) -> None:
    with _client(tmp_path, agent=False) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            session_id = ready["session_id"]
            question_id = ready["question"]["id"]

            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": question_id,
                    "text": "第一次回答",
                }
            )
            first = _recv_until(ws, "score")[-1]
            assert first["duplicate"] is False

            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": question_id,
                    "text": "第二次回答",
                    "retry": True,
                }
            )
            second = _recv_until(ws, "score")[-1]
            assert second["duplicate"] is False
            assert second["question_id"] == question_id

        store = Store(connect(tmp_path / "app.db"))
        try:
            rows = store.session_questions(session_id)
            assert len(rows) == 5
            answered = [row for row in rows if row["score"] is not None]
            assert len(answered) == 1
            assert answered[0]["answer_text"] == "第二次回答"
        finally:
            store.close()


def test_reveal_returns_reference_without_scoring(tmp_path) -> None:
    with _client(tmp_path, agent=False) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            session_id = ready["session_id"]
            question_id = ready["question"]["id"]

            ws.send_json(
                {"type": "reveal", "session_id": session_id, "question_id": question_id}
            )
            reveal = _recv_until(ws, "reveal")[-1]
            assert reveal["question_id"] == question_id
            assert reveal["text"].strip()

        store = Store(connect(tmp_path / "app.db"))
        try:
            row = store.question(question_id)
            assert row["score"] is None
            assert row["answer_text"] is None
        finally:
            store.close()


def test_duplicate_finish_returns_session_finished(tmp_path) -> None:
    with _client(tmp_path, agent=False) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            session_id = ready["session_id"]

            ws.send_json({"type": "finish", "session_id": session_id})
            _recv_until(ws, "session_result")
            ws.send_json({"type": "finish", "session_id": session_id})
            error = _recv_until(ws, "error")[-1]
            assert error.get("code") == "session_finished"


def test_free_talk_tool_failure_keeps_connection_usable(tmp_path) -> None:
    async def failing(arguments):
        return ToolResult.failure(
            "search_web", code="timeout", message="搜索超时"
        )

    with _client(tmp_path, agent=True) as client:
        scripted = ScriptedAgentClient(
            [
                AgentResponse(
                    content="",
                    tool_calls=(
                        AgentToolCall(
                            id="call-1",
                            name="search_web",
                            arguments='{"query": "agent"}',
                        ),
                    ),
                ),
                AgentResponse(content="没查到，先按已有知识说"),
                AgentResponse(content="第二回合"),
            ]
        )
        client.app.state.agent_loop = AgentLoop(
            scripted,
            ToolRegistry(DEFAULT_TOOL_SPECS, {"search_web": failing}),
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "text", "text": "查一下"})
            first = _recv_until(ws, "reply")[-1]
            assert "没查到" in first["text"]

            ws.send_json({"type": "text", "text": "再试一次"})
            second = _recv_until(ws, "reply")[-1]
            assert second["text"].endswith("第二回合")


def test_answer_path_does_not_start_agent(tmp_path) -> None:
    with _client(tmp_path, agent=True) as client:
        scripted = ScriptedAgentClient([AgentResponse(content="不该出现")])
        client.app.state.agent_loop = AgentLoop(
            scripted,
            ToolRegistry(DEFAULT_TOOL_SPECS, {}),
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            ws.send_json(
                {
                    "type": "answer",
                    "session_id": ready["session_id"],
                    "question_id": ready["question"]["id"],
                    "text": "我的回答",
                }
            )
            messages = _recv_until(ws, "score")
            assert all(item["type"] != "agent_status" for item in messages)
            assert scripted.calls == []


def test_teach_context_has_no_rubric_or_answer_key(tmp_path) -> None:
    with _client(tmp_path, agent=True) as client:
        scripted = ScriptedAgentClient([AgentResponse(content="讲解内容")])
        client.app.state.agent_loop = AgentLoop(
            scripted,
            ToolRegistry(DEFAULT_TOOL_SPECS, {}),
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            ws.send_json(
                {
                    "type": "text",
                    "session_id": ready["session_id"],
                    "question_id": ready["question"]["id"],
                    "intent": "clarify",
                    "text": "这题什么意思",
                }
            )
            _recv_until(ws, "teach_reply")
            system = scripted.calls[0]["messages"][0].content
            assert "rubric_json" not in system
            assert "reference_answer" not in system
            assert "answer_key" not in system
            assert "不要声称你已保存" in system
            assert "来源列表由服务端" in system
            assert "原样引用" in system
            assert "不要改数字" in system


def _counts(db_path) -> tuple[int, ...]:
    store = Store(connect(db_path))
    try:
        return tuple(
            int(store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "materials",
                "concept_sources",
                "question_bank",
                "session_questions",
            )
        )
    finally:
        store.close()


def test_web_tool_does_not_write_knowledge_tables(tmp_path) -> None:
    with _client(tmp_path, agent=True) as client:
        registry = ToolRegistry(
            DEFAULT_TOOL_SPECS,
            {"search_web": SearchWebTool(FakeSearch(), today=lambda: "2026-11-25")},
        )
        client.app.state.agent_loop = AgentLoop(
            ScriptedAgentClient(
                [
                    AgentResponse(
                        content="",
                        tool_calls=(
                            AgentToolCall(
                                id="call-1",
                                name="search_web",
                                arguments='{"query": "agent"}',
                            ),
                        ),
                    ),
                    AgentResponse(content="网页回答"),
                ]
            ),
            registry,
        )
        before = _counts(tmp_path / "app.db")
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "text", "text": "联网查 agent"})
            reply = _recv_until(ws, "reply")[-1]
            assert reply["sources"]
            assert reply["web_status"] == "ok"
        assert _counts(tmp_path / "app.db") == before


def test_agent_budget_exhausted_is_visible(tmp_path) -> None:
    calls = [
        AgentResponse(
            content="",
            tool_calls=(
                AgentToolCall(
                    id=f"call-{i}",
                    name="search_materials",
                    arguments='{"query": "a"}',
                ),
            ),
        )
        for i in range(4)
    ] + [
        AgentResponse(
            content="",
            tool_calls=(
                AgentToolCall(
                    id=f"web-{i}",
                    name="search_web",
                    arguments='{"query": "a"}',
                ),
            ),
        )
        for i in range(4)
    ]
    with _client(tmp_path, agent=True) as client:
        client.app.state.agent_loop = _loop(calls + [AgentResponse(content="收口回答")])
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "text", "text": "查满预算"})
            reply = _recv_until(ws, "reply")[-1]
            assert reply["text"].endswith("收口回答")
            assert reply["agent"]["tool_calls"] == 8
            assert reply["agent"]["web_calls"] == 4
            assert reply["agent"]["budget_exhausted"] is True


def test_teach_without_agent_harness_is_not_scored(tmp_path) -> None:
    with _client(tmp_path, agent=False) as client:
        with client.websocket_connect("/ws") as ws:
            ready = _start(ws)
            ws.send_json(
                {
                    "type": "text",
                    "session_id": ready["session_id"],
                    "question_id": ready["question"]["id"],
                    "intent": "teach",
                    "text": "讲讲这题",
                }
            )
            error = _recv_until(ws, "error")[-1]
            assert error["stage"] == "agent"
            assert "未启用" in error["message"]

        store = Store(connect(tmp_path / "app.db"))
        try:
            rows = store.session_questions(ready["session_id"])
            assert all(row["score"] is None for row in rows)
        finally:
            store.close()


def test_duplicate_fifth_answer_replays_after_settle(tmp_path) -> None:
    with _client(tmp_path, agent=False) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "session_start", "kind": "daily"})
            ready = _recv_until(ws, "session_ready")[-1]
            session_id = ready["session_id"]
            question_id = ready["question"]["id"]
            for index in range(5):
                ws.send_json(
                    {
                        "type": "answer",
                        "session_id": session_id,
                        "question_id": question_id,
                        "text": f"回答 {index + 1}",
                    }
                )
                _recv_until(ws, "score")
                if index < 4:
                    question_id = _recv_until(ws, "question")[-1]["id"]
                else:
                    _recv_until(ws, "session_result")
            ws.send_json(
                {
                    "type": "answer",
                    "session_id": session_id,
                    "question_id": question_id,
                    "text": "重复第五题",
                }
            )
            duplicate = _recv_until(ws, "score")[-1]
            assert duplicate["duplicate"] is True
            assert duplicate["score"] is not None


def test_teach_rejects_future_question(tmp_path) -> None:
    with _client(tmp_path, agent=True) as client:
        with client.websocket_connect("/ws") as ws:
            ready = _start(ws)
            session_id = ready["session_id"]
        store = Store(connect(tmp_path / "app.db"))
        try:
            future = store.session_questions(session_id)[-1]
        finally:
            store.close()
        scripted = ScriptedAgentClient([AgentResponse(content="讲解")])
        client.app.state.agent_loop = AgentLoop(
            scripted,
            ToolRegistry(DEFAULT_TOOL_SPECS, {}),
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json(
                {
                    "type": "text",
                    "session_id": session_id,
                    "question_id": future["id"],
                    "intent": "clarify",
                    "text": "这题什么意思",
                }
            )
            error = _recv_until(ws, "error")[-1]
            assert "只能问当前题" in error["message"]
        assert scripted.calls == []


def test_zero_hit_search_sets_teach_mode(tmp_path) -> None:
    async def empty_search(arguments):
        return ToolResult.success(
            "search_materials", {"grounded": False, "results": [], "sources": []}
        )

    with _client(tmp_path, agent=True) as client:
        client.app.state.agent_loop = AgentLoop(
            ScriptedAgentClient(
                [
                    AgentResponse(
                        content="",
                        tool_calls=(
                            AgentToolCall(
                                id="call-1",
                                name="search_materials",
                                arguments='{"query": "不存在"}',
                            ),
                        ),
                    ),
                    AgentResponse(content="回答"),
                ]
            ),
            ToolRegistry(
                DEFAULT_TOOL_SPECS, {"search_materials": empty_search}
            ),
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "text", "text": "查一个没有的东西"})
            reply = _recv_until(ws, "reply")[-1]
            assert reply["mode"] == "teach"
            assert reply["agent"]["tool_calls"] == 1


def test_empty_fallback_gets_general_prefix(tmp_path) -> None:
    with _client(tmp_path, agent=True) as client:
        client.app.state.agent_loop = AgentLoop(
            ScriptedAgentClient([AgentResponse(content="")]),
            ToolRegistry(DEFAULT_TOOL_SPECS, {}),
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "text", "text": "嗨"})
            reply = _recv_until(ws, "reply")[-1]
            assert reply["text"].startswith(
                "材料里没有直接讲到，以下是一般知识："
            )


def test_web_tool_is_labeled_and_gets_note(tmp_path) -> None:
    async def web_search(arguments):
        return ToolResult.success(
            "search_web",
            {
                "status": "ok",
                "sources": [
                    {
                        "kind": "web",
                        "url": "https://example.com/a",
                        "title": "网页",
                        "excerpt": "摘要",
                        "domain": "example.com",
                        "retrieved_at": "2026-11-25",
                    }
                ],
            },
        )

    with _client(tmp_path, agent=True) as client:
        scripted = ScriptedAgentClient(
            [
                AgentResponse(
                    content="",
                    tool_calls=(
                        AgentToolCall(
                            id="call-1",
                            name="search_web",
                            arguments='{"query": "agent"}',
                        ),
                    ),
                ),
                AgentResponse(content="网页回答 [1]"),
            ]
        )
        client.app.state.agent_loop = AgentLoop(
            scripted,
            ToolRegistry(DEFAULT_TOOL_SPECS, {"search_web": web_search}),
        )
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "text", "text": "联网查一下"})
            reply = _recv_until(ws, "reply")[-1]
            assert "网上信息，可能变化" in reply["text"]
        system = scripted.calls[0]["messages"][0].content
        tool_message = next(
            message.content
            for message in scripted.calls[1]["messages"]
            if message.role == "tool"
        )
        assert "未核实外部数据" in tool_message
        assert "材料说" in system
