"""有界工具回合的契约：工具描述、调用、结果、预算与来源整理。

只做数据类型、参数解析、统一错误信封与来源去重；不调用外部服务，不写库。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

AGENT_STEPS: tuple[str, ...] = ("free_talk", "teach", "clarify")

TOOL_SEARCH_MATERIALS = "search_materials"
TOOL_SEARCH_WEB = "search_web"
TOOL_READ_CONCEPT = "read_concept"

MAX_TOOL_CALLS = 8
MAX_CALLS_PER_TOOL = 4
MAX_WEB_CALLS = 4
TURN_DEADLINE_SECONDS = 60.0
MODEL_TIMEOUT_SECONDS = 15.0
MAX_SOURCES = 5
MAX_MATERIAL_RESULTS = 3
MAX_WEB_RESULTS = 3
MAX_MATERIAL_CHARS = 1200
MAX_WEB_CHARS = 600

GENERAL_KNOWLEDGE_PREFIX = "材料里没有直接讲到，以下是一般知识："

CODE_TIMEOUT = "timeout"
CODE_PROVIDER_ERROR = "provider_error"
CODE_INVALID_ARGUMENTS = "invalid_arguments"
CODE_UNKNOWN_TOOL = "unknown_tool"
CODE_BUDGET_EXHAUSTED = "budget_exhausted"
CODE_NOT_CONFIGURED = "not_configured"
CODE_NOT_FOUND = "not_found"
CODE_INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """一个工具对模型可见的描述与执行上限。"""

    name: str
    description: str
    parameters: Mapping[str, Any]
    timeout_seconds: float
    allowed_steps: tuple[str, ...] = AGENT_STEPS

    def as_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }


@dataclass(frozen=True, slots=True)
class ToolCall:
    """模型返回的一次工具调用；arguments 是原始 JSON 字符串。"""

    id: str
    name: str
    arguments: str = "{}"


@dataclass(frozen=True, slots=True)
class ToolError:
    code: str
    message: str
    retryable: bool = True
    hint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "hint": self.hint,
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    """统一工具结果信封；失败也返回本类型，不抛异常。"""

    ok: bool
    tool: str
    data: Mapping[str, Any] | None = None
    error: ToolError | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "data": dict(self.data) if self.data is not None else None,
            "error": self.error.as_dict() if self.error is not None else None,
        }

    @classmethod
    def success(cls, tool: str, data: Mapping[str, Any] | None = None) -> "ToolResult":
        return cls(ok=True, tool=tool, data=data or {})

    @classmethod
    def failure(
        cls,
        tool: str,
        *,
        code: str,
        message: str,
        retryable: bool = True,
        hint: str = "",
    ) -> "ToolResult":
        return cls(
            ok=False,
            tool=tool,
            error=ToolError(
                code=code, message=message, retryable=retryable, hint=hint
            ),
        )


@dataclass(frozen=True, slots=True)
class ToolBudget:
    max_tool_calls: int = MAX_TOOL_CALLS
    max_calls_per_tool: int = MAX_CALLS_PER_TOOL
    max_web_calls: int = MAX_WEB_CALLS
    deadline_seconds: float = TURN_DEADLINE_SECONDS

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_tool_calls": self.max_tool_calls,
            "max_calls_per_tool": self.max_calls_per_tool,
            "max_web_calls": self.max_web_calls,
            "deadline_seconds": self.deadline_seconds,
        }


class ToolArgumentError(ValueError):
    """工具参数不是合法的 JSON 对象。"""


def parse_arguments(raw: str) -> dict[str, Any]:
    if not (raw or "").strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolArgumentError(f"参数不是合法 JSON：{exc.msg}") from exc
    if not isinstance(value, dict):
        raise ToolArgumentError("参数必须是 JSON 对象")
    return value


def clip_text(text: Any, limit: int) -> str:
    """按字符截断，保留尾部省略号；不改变未超限文本。"""
    value = str(text or "")
    if limit <= 0 or len(value) <= limit:
        return value
    return value[:limit].rstrip() + "…"


def source_keys(item: Mapping[str, Any]) -> list[str]:
    """一条来源可能同时有 chunk_id 与 url；任一命中都算重复。"""
    keys: list[str] = []
    for key in ("chunk_id", "url", "source_url"):
        value = item.get(key)
        if value:
            keys.append(str(value))
    return keys


def collect_sources(
    results: Sequence[ToolResult], *, limit: int = MAX_SOURCES
) -> list[dict[str, Any]]:
    """按工具调用顺序汇总 sources，按 chunk_id/URL 去重并重新编号。"""
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    for result in results:
        if not result.ok or not result.data:
            continue
        items = result.data.get("sources")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            keys = source_keys(item)
            if any(key in seen for key in keys):
                continue
            seen.update(keys)
            source = dict(item)
            source["index"] = len(sources) + 1
            sources.append(source)
            if len(sources) >= limit:
                return sources
    return sources


class ToolHandler(Protocol):
    async def __call__(self, arguments: Mapping[str, Any]) -> ToolResult: ...


class ToolRegistry:
    """按步骤过滤工具，并把参数/超时/异常折叠成 ToolResult。"""

    def __init__(
        self,
        specs: Sequence[ToolSpec],
        handlers: Mapping[str, ToolHandler],
    ) -> None:
        self._specs: dict[str, ToolSpec] = {spec.name: spec for spec in specs}
        self._handlers = dict(handlers)

    def specs_for(self, step: str) -> tuple[ToolSpec, ...]:
        if step not in AGENT_STEPS:
            return ()
        return tuple(
            spec for spec in self._specs.values() if step in spec.allowed_steps
        )

    def spec(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    async def execute(
        self,
        call: ToolCall,
        *,
        step: str,
        timeout_seconds: float | None = None,
    ) -> ToolResult:
        spec = self._specs.get(call.name)
        if spec is None or step not in spec.allowed_steps:
            available = ", ".join(item.name for item in self.specs_for(step))
            return ToolResult.failure(
                call.name,
                code=CODE_UNKNOWN_TOOL,
                message=f"未知工具：{call.name}",
                retryable=False,
                hint=f"可用工具：{available or '无'}",
            )

        try:
            arguments = parse_arguments(call.arguments)
        except ToolArgumentError as exc:
            return ToolResult.failure(
                call.name,
                code=CODE_INVALID_ARGUMENTS,
                message=str(exc),
                hint="参数必须是 JSON 对象",
            )

        handler = self._handlers.get(call.name)
        if handler is None:
            return ToolResult.failure(
                call.name,
                code=CODE_UNKNOWN_TOOL,
                message=f"工具未注册：{call.name}",
                retryable=False,
            )

        timeout = (
            spec.timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        try:
            result = await asyncio.wait_for(handler(arguments), timeout=timeout)
        except asyncio.TimeoutError:
            return ToolResult.failure(
                call.name,
                code=CODE_TIMEOUT,
                message=f"{call.name} 超过 {timeout:g} 秒",
                hint="可以换更短的关键词，或直接用已有结果回答",
            )
        except Exception as exc:  # pragma: no cover - 适配器 bug 的兜底
            return ToolResult.failure(
                call.name,
                code=CODE_INTERNAL_ERROR,
                message=f"{call.name} 内部错误：{exc}",
                retryable=False,
                hint="请换方法或直接回答",
            )

        if not isinstance(result, ToolResult):
            return ToolResult.failure(
                call.name,
                code=CODE_INTERNAL_ERROR,
                message=f"{call.name} 返回了错误的结果类型",
                retryable=False,
            )
        return result


SEARCH_MATERIALS_SPEC = ToolSpec(
    name=TOOL_SEARCH_MATERIALS,
    description=(
        "在用户本地已确认的学习材料里检索。返回材料片段与出处。"
        "回答概念、找材料依据、教学/澄清时优先使用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索关键词，尽量短且具体",
                "minLength": 1,
                "maxLength": 200,
            },
            "top_k": {
                "type": "integer",
                "description": "返回条数",
                "minimum": 1,
                "maximum": 5,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    timeout_seconds=5.0,
)

SEARCH_WEB_SPEC = ToolSpec(
    name=TOOL_SEARCH_WEB,
    description=(
        "在外部网页搜索。只在用户明确要求联网、问题有时效性、"
        "或本地材料不足时使用；结果只作对话来源，不写知识库。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词，尽量短且具体",
                "minLength": 1,
                "maxLength": 200,
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    timeout_seconds=8.0,
)

READ_CONCEPT_SPEC = ToolSpec(
    name=TOOL_READ_CONCEPT,
    description=(
        "读取一个已确认概念的简称、定义、别名与主出处。"
        "用于快速确认“这个词是什么”，不需要检索整段材料。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "concept": {
                "type": "string",
                "description": "概念 id、名称或别名",
                "minLength": 1,
                "maxLength": 80,
            }
        },
        "required": ["concept"],
        "additionalProperties": False,
    },
    timeout_seconds=1.0,
)

DEFAULT_TOOL_SPECS: tuple[ToolSpec, ...] = (
    SEARCH_MATERIALS_SPEC,
    SEARCH_WEB_SPEC,
    READ_CONCEPT_SPEC,
)
