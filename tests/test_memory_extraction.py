from __future__ import annotations

import pytest

from core.memory_extraction import (
    MemoryParseError,
    build_extraction_messages,
    parse_memories,
    normalize_text,
)

USER_TEXTS = [
    {
        "text": "我更喜欢先看例子，再看定义",
        "question_id": 7,
        "question_text": "什么是 agent 循环",
    },
    {
        "text": "听到大段定义会有点烦",
        "question_id": 8,
        "question_text": "解释一下 workflow",
    },
]


def test_build_extraction_messages_marks_question_as_context() -> None:
    system, user = build_extraction_messages(USER_TEXTS)
    assert "用户记忆提炼器" in system
    assert "题目：什么是 agent 循环" in user
    assert "用户原话：我更喜欢先看例子，再看定义" in user
    assert "assistant" not in user.lower()


def test_parse_valid_memories_and_source_question() -> None:
    raw = (
        '{"memories":['
        '{"kind":"preference","text":"更习惯先看例子",'
        '"source_quote":"更喜欢先看例子"},'
        '{"kind":"feeling","text":"听到大段定义会烦",'
        '"source_quote":"听到大段定义会有点烦"}'
        ']}'
    )
    drafts = parse_memories(raw, USER_TEXTS)
    assert [(d.kind, d.text, d.source_question_id) for d in drafts] == [
        ("preference", "更习惯先看例子", 7),
        ("feeling", "听到大段定义会烦", 8),
    ]


def test_parse_memories_must_be_list() -> None:
    with pytest.raises(MemoryParseError):
        parse_memories('{"memories":{}}', USER_TEXTS)


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(MemoryParseError):
        parse_memories("不是 JSON", USER_TEXTS)


def test_parse_drops_bad_kind() -> None:
    raw = '{"memories":[{"kind":"diagnosis","text":"怕公式","source_quote":"怕公式"}]}'
    assert parse_memories(raw, USER_TEXTS) == []


def test_parse_drops_long_text_and_quote() -> None:
    raw = (
        '{"memories":['
        '{"kind":"quote","text":"' + "长" * 101 + '","source_quote":"怕公式"},'
        '{"kind":"quote","text":"怕公式","source_quote":"' + "长" * 201 + '"}'
        ']}'
    )
    assert parse_memories(raw, USER_TEXTS) == []


def test_parse_drops_quote_not_in_user_text() -> None:
    raw = '{"memories":[{"kind":"quote","text":"怕公式","source_quote":"我不怕公式"}]}'
    assert parse_memories(raw, USER_TEXTS) == []


def test_parse_accepts_whitespace_normalized_quote() -> None:
    raw = '{"memories":[{"kind":"quote","text":"怕公式","source_quote":"我 更喜欢 先看例子"}]}'
    drafts = parse_memories(raw, USER_TEXTS)
    assert len(drafts) == 1
    assert drafts[0].source_question_id == 7


def test_parse_drops_diagnostic_words() -> None:
    raw = (
        '{"memories":[{"kind":"feeling","text":"用户有数学焦虑",'
        '"source_quote":"我更喜欢先看例子"}]}'
    )
    assert parse_memories(raw, USER_TEXTS) == []


def test_parse_drops_progress_words() -> None:
    raw = (
        '{"memories":[{"kind":"quote","text":"这道题第 3 题掌握度不够",'
        '"source_quote":"我更喜欢先看例子"}]}'
    )
    assert parse_memories(raw, USER_TEXTS) == []


def test_parse_takes_first_five_and_dedupes_same_text() -> None:
    items = [
        '{"kind":"quote","text":"怕公式","source_quote":"我更喜欢先看例子"}',
        '{"kind":"quote","text":"怕公式。","source_quote":"听到大段定义会有点烦"}',
        '{"kind":"quote","text":"怕推导","source_quote":"我更喜欢先看例子"}',
        '{"kind":"quote","text":"怕证明","source_quote":"我更喜欢先看例子"}',
        '{"kind":"quote","text":"怕符号","source_quote":"我更喜欢先看例子"}',
        '{"kind":"quote","text":"第六条应被截断","source_quote":"我更喜欢先看例子"}',
    ]
    raw = '{"memories":[' + ",".join(items) + "]}"
    drafts = parse_memories(raw, USER_TEXTS)
    assert [draft.text for draft in drafts] == ["怕公式", "怕推导", "怕证明", "怕符号"]


def test_normalize_text_strips_trailing_punctuation() -> None:
    assert normalize_text("  更习惯  先看例子。 ") == "更习惯 先看例子"
