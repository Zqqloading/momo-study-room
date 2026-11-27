"""OpenAI SDK 适配器：只负责发请求、解析 tool_calls，不含业务规则。

MiMo 与 DeepSeek 都走 OpenAI 兼容端点；私有 header 用 default_headers。
"""

from __future__ import annotations

from typing import Any, Sequence

from openai import AsyncOpenAI

from core.agent_tools import ToolSpec
from core.ports import AgentClientError, AgentMessage, AgentResponse, AgentToolCall


def _message_payload(message: AgentMessage) -> dict[str, Any]:
    if message.role == "tool":
        return {
            "role": "tool",
            "content": message.content,
            "tool_call_id": message.tool_call_id,
        }
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in message.tool_calls
            ],
        }
    return {"role": message.role, "content": message.content}


class OpenAIAgentClient:
    name = "openai-agent"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 15.0,
        max_retries: int = 1,
        default_headers: dict[str, str] | None = None,
        http_client: Any | None = None,
    ) -> None:
        self.model = model
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=default_headers,
            http_client=http_client,
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def complete(
        self,
        messages: Sequence[AgentMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        tool_choice: str | None = "auto",
        timeout_seconds: float = 15.0,
    ) -> AgentResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_payload(message) for message in messages],
        }
        if tools:
            payload["tools"] = [spec.as_openai() for spec in tools]
            if tool_choice:
                payload["tool_choice"] = tool_choice

        client = self._client
        if timeout_seconds and timeout_seconds > 0:
            client = client.with_options(timeout=timeout_seconds)
        try:
            response = await client.chat.completions.create(**payload)
        except Exception as exc:
            raise AgentClientError(f"模型调用失败：{exc}") from exc

        try:
            choice = response.choices[0]
            message = choice.message
        except (AttributeError, IndexError, TypeError) as exc:
            raise AgentClientError("模型响应缺少 choices") from exc

        calls = tuple(
            AgentToolCall(
                id=call.id,
                name=call.function.name,
                arguments=call.function.arguments or "{}",
            )
            for call in (message.tool_calls or ())
        )
        return AgentResponse(
            content=message.content or "",
            tool_calls=calls,
            finish_reason=choice.finish_reason,
        )


class FakeAgentClient:
    """离线/测试用：不调模型，返回固定回复。"""

    name = "fake-agent"

    def __init__(self, answer: str = "（离线）我暂时不能查资料，先按一般知识回答。") -> None:
        self.answer = answer

    async def aclose(self) -> None:
        return None

    async def complete(
        self,
        messages: Sequence[AgentMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        tool_choice: str | None = "auto",
        timeout_seconds: float = 15.0,
    ) -> AgentResponse:
        return AgentResponse(content=self.answer)
