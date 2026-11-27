from __future__ import annotations

from dataclasses import replace
from datetime import date

from core.agent_loop import build_system_prompt
from core.agent_steps import build_free_talk_brief
from core.discipline import D1, D2
from core.free_talk import build_free_talk_messages
from core.persona import default_life_pool, default_persona
from core.prompt import (
    PromptBlocks,
    compose_system_prompt,
    memory_block,
    tone_block,
)


def test_blocks_are_joined_in_fixed_order() -> None:
    prompt = compose_system_prompt(
        PromptBlocks(
            role="R",
            persona="P",
            tone="T",
            memory="M",
            task="K",
            context="C",
            discipline="D",
            data="X",
        )
    )
    assert prompt == "R\n\nP\n\nT\n\nM\n\nK\n\nC\n\nD\n\nX"


def test_empty_blocks_are_skipped() -> None:
    assert compose_system_prompt(PromptBlocks(role="R", task="K")) == "R\n\nK"
    assert compose_system_prompt(PromptBlocks()) == ""


def test_data_is_always_last() -> None:
    prompt = compose_system_prompt(
        PromptBlocks(role="R", data="DATA", discipline="D", persona="P")
    )
    assert prompt.endswith("DATA")
    assert prompt.index("P") < prompt.index("D") < prompt.index("DATA")


def test_tone_and_memory_blocks_are_optional() -> None:
    assert tone_block("") == ""
    assert memory_block("") == ""
    assert "【当前语气】" in tone_block("轻快一点。")
    assert "【用户要求回忆】" in memory_block("- 更喜欢先看例子")


def test_free_talk_prompt_order_and_no_life() -> None:
    content = build_free_talk_messages(
        [],
        "今天好累",
        "chat",
        persona_block="PERSONA",
        tone_hint="TONE",
        memory_context="MEMORY",
    )[0].content
    life = default_life_pool().for_date(date.today().isoformat())
    assert life
    assert life not in content
    assert content.index("PERSONA") < content.index("TONE") < content.index("MEMORY")
    assert content.index("MEMORY") < content.index("【底线")


def test_agent_prompt_order_and_data_last() -> None:
    brief = build_free_talk_brief(
        today="2026-11-26",
        tone_hint="TONE",
        memory_context="MEMORY",
    )
    content = build_system_prompt(brief)
    life = default_life_pool().for_date(date.today().isoformat())
    assert life
    assert life not in content
    assert content.index("TONE") < content.index("MEMORY")
    assert content.index("【底线") < content.index("当前工单：")
    assert content.rstrip().endswith("}")


def test_all_entries_disabled_still_has_discipline() -> None:
    config = default_persona()
    disabled = replace(
        config,
        entries=tuple(replace(entry, enabled=False) for entry in config.entries),
    )
    brief = build_free_talk_brief(today="2026-11-26")
    content = build_system_prompt(brief, persona=disabled)
    assert "【她是谁】" not in content
    assert D1 in content
    assert D2 in content
