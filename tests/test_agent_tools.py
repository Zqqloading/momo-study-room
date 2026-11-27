from __future__ import annotations

import asyncio

import pytest

from core.agent_tools import (
    CODE_INTERNAL_ERROR,
    CODE_INVALID_ARGUMENTS,
    CODE_TIMEOUT,
    CODE_UNKNOWN_TOOL,
    DEFAULT_TOOL_SPECS,
    MAX_SOURCES,
    READ_CONCEPT_SPEC,
    SEARCH_MATERIALS_SPEC,
    SEARCH_WEB_SPEC,
    ToolBudget,
    ToolCall,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    clip_text,
    collect_sources,
    parse_arguments,
)


def test_default_tools_are_openai_function_specs() -> None:
    names = [spec.name for spec in DEFAULT_TOOL_SPECS]
    assert names == ["search_materials", "search_web", "read_concept"]
    for spec in DEFAULT_TOOL_SPECS:
        shape = spec.as_openai()
        assert shape["type"] == "function"
        assert shape["function"]["name"] == spec.name
        assert shape["function"]["parameters"]["type"] == "object"


def test_specs_are_filtered_by_step() -> None:
    registry = ToolRegistry(DEFAULT_TOOL_SPECS, {})
    for step in ("free_talk", "teach", "clarify"):
        assert {spec.name for spec in registry.specs_for(step)} == {
            "search_materials",
            "search_web",
            "read_concept",
        }
    assert registry.specs_for("answer") == ()


def test_execute_success_and_as_dict() -> None:
    async def handler(arguments):
        assert arguments == {"query": "agent loop"}
        return ToolResult.success(
            SEARCH_MATERIALS_SPEC.name,
            {"sources": [{"chunk_id": "c1", "url": "u1", "excerpt": "x"}]},
        )

    registry = ToolRegistry([SEARCH_MATERIALS_SPEC], {"search_materials": handler})
    result = asyncio.run(
        registry.execute(
            ToolCall(id="call-1", name="search_materials", arguments='{"query":"agent loop"}'),
            step="free_talk",
        )
    )
    assert result.ok is True
    assert result.data is not None
    assert result.as_dict()["data"]["sources"][0]["chunk_id"] == "c1"
    assert result.as_dict()["error"] is None


def test_execute_invalid_arguments() -> None:
    async def handler(arguments):  # pragma: no cover - 不应被调用
        raise AssertionError("handler should not run")

    registry = ToolRegistry([SEARCH_MATERIALS_SPEC], {"search_materials": handler})
    result = asyncio.run(
        registry.execute(
            ToolCall(id="call-1", name="search_materials", arguments="{"),
            step="free_talk",
        )
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_INVALID_ARGUMENTS


def test_execute_unknown_tool_includes_hint() -> None:
    registry = ToolRegistry(DEFAULT_TOOL_SPECS, {})
    result = asyncio.run(
        registry.execute(
            ToolCall(id="call-1", name="score_answer", arguments="{}"),
            step="free_talk",
        )
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_UNKNOWN_TOOL
    assert "search_materials" in result.error.hint


def test_execute_disallowed_step_is_unknown() -> None:
    spec = ToolSpec(
        name="only_free_talk",
        description="test",
        parameters={"type": "object", "properties": {}},
        timeout_seconds=1.0,
        allowed_steps=("free_talk",),
    )

    async def handler(arguments):
        return ToolResult.success(spec.name, {})

    registry = ToolRegistry([spec], {spec.name: handler})
    result = asyncio.run(
        registry.execute(
            ToolCall(id="call-1", name=spec.name, arguments="{}"), step="teach"
        )
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_UNKNOWN_TOOL


def test_execute_timeout_returns_observation() -> None:
    async def handler(arguments):
        await asyncio.sleep(0.05)
        return ToolResult.success(SEARCH_WEB_SPEC.name, {})

    registry = ToolRegistry([SEARCH_WEB_SPEC], {"search_web": handler})
    result = asyncio.run(
        registry.execute(
            ToolCall(id="call-1", name="search_web", arguments='{"query":"x"}'),
            step="teach",
            timeout_seconds=0.01,
        )
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_TIMEOUT


def test_execute_handler_error_is_internal_error() -> None:
    async def handler(arguments):
        raise RuntimeError("boom")

    registry = ToolRegistry([READ_CONCEPT_SPEC], {"read_concept": handler})
    result = asyncio.run(
        registry.execute(
            ToolCall(id="call-1", name="read_concept", arguments='{"concept":"x"}'),
            step="clarify",
        )
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_INTERNAL_ERROR


def test_collect_sources_dedupes_caps_and_reindexes() -> None:
    first = ToolResult.success(
        "search_materials",
        {
            "sources": [
                {"chunk_id": "a", "url": "u1", "excerpt": "A"},
                {"chunk_id": "a", "url": "u1", "excerpt": "A duplicate"},
                {"chunk_id": "b", "url": "u2", "excerpt": "B"},
            ]
        },
    )
    second = ToolResult.success(
        "search_web",
        {
            "sources": [
                {"url": "u2", "excerpt": "B duplicate"},
                {"url": "u3", "excerpt": "C"},
                {"url": "u4", "excerpt": "D"},
                {"url": "u5", "excerpt": "E"},
            ]
        },
    )
    failed = ToolResult.failure(
        "search_web", code=CODE_TIMEOUT, message="timeout"
    )
    sources = collect_sources([first, failed, second])
    assert len(sources) == MAX_SOURCES
    assert [source["index"] for source in sources] == [1, 2, 3, 4, 5]
    assert [source["url"] for source in sources] == ["u1", "u2", "u3", "u4", "u5"]


def test_clip_text() -> None:
    assert clip_text("abc", 10) == "abc"
    clipped = clip_text("a" * 20, 10)
    assert clipped == "aaaaaaaaaa…"


def test_parse_arguments() -> None:
    assert parse_arguments("") == {}
    assert parse_arguments("{}") == {}
    assert parse_arguments('{"query":"x"}') == {"query": "x"}
    with pytest.raises(ValueError):
        parse_arguments("[]")
    with pytest.raises(ValueError):
        parse_arguments("{")


def test_tool_budget_dict() -> None:
    assert ToolBudget().as_dict() == {
        "max_tool_calls": 8,
        "max_calls_per_tool": 4,
        "max_web_calls": 4,
        "deadline_seconds": 60.0,
    }


UNEXPOSED_TOOL_NAMES = (
    "generate_questions",
    "score_answer",
    "propose_unit",
    "build_session_plan",
    "start_unit",
    "save_answer",
    "finish_session",
    "resume_session",
    "save_conversation",
    "skip_question",
    "repeat_question",
    "end_session",
    "ingest_material",
    "backup_db",
    "free_talk",
    "teach",
    "clarify",
)


@pytest.mark.parametrize("name", UNEXPOSED_TOOL_NAMES)
def test_non_agent_tools_are_not_exposed(name: str) -> None:
    registry = ToolRegistry(DEFAULT_TOOL_SPECS, {})
    result = asyncio.run(
        registry.execute(
            ToolCall(id="call-1", name=name, arguments="{}"),
            step="free_talk",
        )
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == CODE_UNKNOWN_TOOL
