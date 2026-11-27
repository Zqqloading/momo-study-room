from __future__ import annotations

from pathlib import Path

from core.ports import AgentMessage, AgentResponse, AgentToolCall

CORE_DIR = Path(__file__).resolve().parents[1] / "core"


def test_core_has_no_agent_sdk_or_http_imports() -> None:
    for path in CORE_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for forbidden in (
            "import openai",
            "from openai",
            "import httpx",
            "from httpx",
        ):
            assert forbidden not in text, f"{path.name} contains {forbidden}"


def test_agent_message_defaults() -> None:
    message = AgentMessage(role="user", content="嗨")
    assert message.tool_calls == ()
    assert message.tool_call_id == ""

    tool_message = AgentMessage(
        role="tool", content='{"ok": true}', tool_call_id="call-1"
    )
    assert tool_message.tool_call_id == "call-1"


def test_agent_response_defaults() -> None:
    response = AgentResponse(content="好")
    assert response.tool_calls == ()
    assert response.finish_reason is None

    call = AgentToolCall(id="call-1", name="search_materials", arguments="{}")
    response = AgentResponse(
        content="", tool_calls=(call,), finish_reason="tool_calls"
    )
    assert response.tool_calls == (call,)
    assert response.finish_reason == "tool_calls"
