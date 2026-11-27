from __future__ import annotations

from core.discipline import D1, D2, D5
from core.free_talk import (
    CHAT_TASK,
    MATERIAL_MAX_CHARS,
    MAX_HISTORY_MESSAGES,
    TEACH_TASK,
    build_free_talk_messages,
    format_material_context,
    format_progress,
)
from core.ports import ChatMessage
from core.persona import role_line


def test_progress_summary_mentions_mastery_and_recent_scores() -> None:
    progress = format_progress(
        [("Agent 循环", 2, "2026-11-24"), ("工具调用", 0, None)],
        [("2026-11-23", "daily", "completed", 50.0)],
    )
    assert "Agent 循环：mastery 2，2026-11-24 复习" in progress
    assert "工具调用：mastery 0" in progress
    assert "2026-11-23 daily completed 50 分" in progress


def test_empty_progress_is_not_injected() -> None:
    messages = build_free_talk_messages([], "今天好累", "chat", "")
    content = messages[0].content
    assert role_line() in content
    assert CHAT_TASK in content
    assert "当前学习进度" not in content
    assert D1 in content
    assert D2 in content
    assert D5 not in content


def test_progress_is_appended_to_system_prompt() -> None:
    progress = "当前学习进度：\n- Agent 循环：mastery 2"
    messages = build_free_talk_messages([], "我学到哪了", "chat", progress)
    assert "当前学习进度" in messages[0].content
    assert "不要逐条复述" in messages[0].content


def test_history_is_truncated_to_window() -> None:
    history = [ChatMessage(role="user", content=f"m{index}") for index in range(30)]
    messages = build_free_talk_messages(history, "新问题", "teach")

    assert TEACH_TASK in messages[0].content
    assert len(messages) == 1 + MAX_HISTORY_MESSAGES + 1
    assert messages[1].content == "m18"
    assert messages[-1] == ChatMessage(role="user", content="新问题")


def test_chat_mode_uses_chat_prompt() -> None:
    messages = build_free_talk_messages([], "今天好累", "chat")
    assert CHAT_TASK in messages[0].content
    assert TEACH_TASK not in messages[0].content


def test_teach_task_allows_one_followup() -> None:
    messages = build_free_talk_messages([], "什么是 agent", "teach")
    content = messages[0].content
    assert "不要反问" not in content
    assert "追问一句" in content
    assert D5 in content


def test_persona_tone_memory_blocks_are_injected() -> None:
    messages = build_free_talk_messages(
        [],
        "今天有点累",
        "chat",
        persona_block="【她是谁】\n- 我是 MOMO",
        tone_hint="语气放轻一点。",
        memory_context="- 更喜欢先看例子",
    )
    content = messages[0].content
    assert "【她是谁】" in content
    assert "【当前语气】" in content
    assert "语气放轻一点。" in content
    assert "【用户要求回忆】" in content
    assert "更喜欢先看例子" in content


def test_material_context_is_numbered_and_truncated() -> None:
    items = [
        {
            "index": 1,
            "text": "甲" * (MATERIAL_MAX_CHARS + 20),
            "excerpt": "大模型会自作主张加需求。",
        }
    ]
    context = format_material_context(items)
    assert "[1]" in context
    assert "…" in context
    assert "出处摘录：大模型会自作主张加需求。" in context
    assert len(context) < MATERIAL_MAX_CHARS + 100


def test_grounded_prompt_requires_citation() -> None:
    messages = build_free_talk_messages(
        [],
        "什么是 agent",
        "teach",
        material_context="[1] Agent 是观察、决策、行动的循环。",
        grounded=True,
    )
    assert "只依据材料摘录" in messages[0].content
    assert "[编号]" in messages[0].content


def test_no_hit_teach_prompt_says_no_material() -> None:
    messages = build_free_talk_messages([], "什么是 agent", "teach", grounded=False)
    assert "材料里没有" in messages[0].content
    assert "这不是材料内容" in messages[0].content


def test_no_hit_chat_prompt_does_not_hard_refuse() -> None:
    messages = build_free_talk_messages([], "今天好累", "chat", grounded=False)
    assert "闲聊不必提材料" in messages[0].content
