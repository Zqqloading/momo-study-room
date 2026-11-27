from __future__ import annotations

import asyncio
import json

import httpx2
import pytest

from bff.agent_llm import OpenAIAgentClient
from core.agent_tools import SEARCH_MATERIALS_SPEC
from core.ports import AgentClientError, AgentMessage, AgentToolCall


def _completion(message: dict, finish_reason: str = "stop") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {"index": 0, "message": message, "finish_reason": finish_reason}
        ],
    }


def _client(handler, *, max_retries: int = 0) -> OpenAIAgentClient:
    transport = httpx2.MockTransport(handler)
    http_client = httpx2.AsyncClient(transport=transport)
    return OpenAIAgentClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        max_retries=max_retries,
        http_client=http_client,
    )


def test_complete_parses_tool_call_and_final_text() -> None:
    seen: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        seen.append(body)
        if len(seen) == 1:
            assert body["tools"][0]["function"]["name"] == "search_materials"
            return httpx2.Response(
                200,
                json=_completion(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "search_materials",
                                    "arguments": '{"query": "agent"}',
                                },
                            }
                        ],
                    },
                    "tool_calls",
                ),
            )
        return httpx2.Response(
            200, json=_completion({"role": "assistant", "content": "最终回答"})
        )

    async def run() -> None:
        client = _client(handler)
        try:
            first = await client.complete(
                [AgentMessage(role="user", content="查一下")],
                tools=(SEARCH_MATERIALS_SPEC,),
            )
            assert first.content == ""
            assert first.tool_calls == (
                AgentToolCall(
                    id="call_1",
                    name="search_materials",
                    arguments='{"query": "agent"}',
                ),
            )
            assert first.finish_reason == "tool_calls"

            second = await client.complete(
                [
                    AgentMessage(
                        role="assistant",
                        tool_calls=first.tool_calls,
                    ),
                    AgentMessage(
                        role="tool",
                        content='{"ok": true}',
                        tool_call_id="call_1",
                    ),
                ]
            )
            assert second.content == "最终回答"
            assert second.tool_calls == ()
        finally:
            await client.aclose()

    asyncio.run(run())
    assert seen[1]["messages"][-1]["role"] == "tool"
    assert seen[1]["messages"][-1]["tool_call_id"] == "call_1"
    assert "tools" not in seen[1]


def test_complete_without_tools_omits_tools() -> None:
    seen: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200, json=_completion({"role": "assistant", "content": "好"})
        )

    async def run() -> None:
        client = _client(handler)
        try:
            response = await client.complete([AgentMessage(role="user", content="嗨")])
            assert response.content == "好"
        finally:
            await client.aclose()

    asyncio.run(run())
    assert "tools" not in seen[0]


def test_complete_wraps_provider_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            500,
            json={"error": {"message": "boom", "type": "server_error"}},
        )

    async def run() -> None:
        client = _client(handler)
        try:
            with pytest.raises(AgentClientError):
                await client.complete([AgentMessage(role="user", content="嗨")])
        finally:
            await client.aclose()

    asyncio.run(run())
