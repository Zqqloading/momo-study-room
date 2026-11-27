from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.memory import (
    DORMANT_THRESHOLD,
    HALF_LIFE_DAYS,
    compose_preamble,
    current_strength,
    extract_clue,
    is_dormant,
    rank_for_opening,
    recall_update,
    render_memory_line,
    render_opening,
)

NOW = datetime(2026, 11, 26, 10, 0, 0)


def _memory(
    memory_id: int = 1,
    *,
    kind: str = "quote",
    text: str = "更习惯先看例子",
    source_quote: str = "我更喜欢先看例子",
    strength: float = 1.0,
    half_life_days: float = HALF_LIFE_DAYS,
    last_recalled_at: str = "2026-11-26T10:00:00",
    recall_count: int = 0,
) -> dict:
    return {
        "id": memory_id,
        "kind": kind,
        "text": text,
        "source_quote": source_quote,
        "strength": strength,
        "half_life_days": half_life_days,
        "last_recalled_at": last_recalled_at,
        "recall_count": recall_count,
    }


def test_current_strength_halves_every_fourteen_days() -> None:
    memory = _memory()
    assert current_strength(memory, NOW) == pytest.approx(1.0)
    assert current_strength(memory, NOW + timedelta(days=7)) == pytest.approx(
        0.5 ** 0.5
    )
    assert current_strength(memory, NOW + timedelta(days=14)) == pytest.approx(0.5)
    assert current_strength(memory, NOW + timedelta(days=28)) == pytest.approx(0.25)


def test_current_strength_uses_kind_strength() -> None:
    preference = _memory(kind="preference", strength=0.75)
    feeling = _memory(kind="feeling", strength=0.5)
    assert current_strength(preference, NOW) == pytest.approx(0.75)
    assert current_strength(feeling, NOW) == pytest.approx(0.5)


def test_dormant_threshold() -> None:
    old = _memory(last_recalled_at="2026-09-01T10:00:00")
    assert current_strength(old, NOW) < DORMANT_THRESHOLD
    assert is_dormant(old, NOW)
    assert not is_dormant(_memory(), NOW)


def test_recall_keeps_strength_and_rerolls_half_life() -> None:
    memory = _memory(strength=1.0, last_recalled_at="2026-11-12T10:00:00")
    updates = recall_update(memory, NOW, rng=lambda low, high: high)
    assert updates["strength"] == pytest.approx(current_strength(memory, NOW))
    assert updates["half_life_days"] == pytest.approx(21.0)
    assert updates["last_recalled_at"] == "2026-11-26T10:00:00"
    assert updates["recall_count"] == 1

    updates = recall_update(memory, NOW, rng=lambda low, high: low)
    assert updates["half_life_days"] == pytest.approx(7.0)


def test_explicit_recall_wakes_dormant_to_tenth() -> None:
    dormant = _memory(last_recalled_at="2026-08-01T10:00:00")
    assert current_strength(dormant, NOW) < 0.05
    updates = recall_update(dormant, NOW, strong=True)
    assert updates["strength"] == pytest.approx(0.1)


def test_explicit_recall_does_not_cap_active_strength() -> None:
    active = _memory(strength=0.4)
    updates = recall_update(active, NOW, strong=True)
    assert updates["strength"] == pytest.approx(0.4)


def test_rank_filters_dormant_and_sorts() -> None:
    newest = _memory(1, strength=1.0, last_recalled_at="2026-11-26T10:00:00")
    older = _memory(2, strength=1.0, last_recalled_at="2026-11-12T10:00:00")
    strongest = _memory(3, strength=1.2)
    dormant = _memory(4, last_recalled_at="2026-08-01T10:00:00")
    ranked = rank_for_opening([newest, older, strongest, dormant], NOW)
    assert [memory["id"] for memory in ranked] == [3, 1, 2]


def test_rank_tie_breaks_by_oldest_recall() -> None:
    recently = _memory(1, strength=0.5, last_recalled_at="2026-11-26T10:00:00")
    long_ago = _memory(2, strength=1.0, last_recalled_at="2026-11-12T10:00:00")
    ranked = rank_for_opening([recently, long_ago], NOW)
    assert [memory["id"] for memory in ranked] == [2, 1]


def test_render_opening_takes_at_most_three() -> None:
    memories = [_memory(index, strength=0.5, text=f"偏好{index}") for index in range(1, 6)]
    block = render_opening(memories, NOW)
    assert len(block.selected) == 3
    assert block.text.startswith("先想起几件你说过的事：")
    assert block.text.endswith("。")


def test_render_opening_respects_char_budget() -> None:
    memories = [
        _memory(
            index,
            kind="preference",
            text="很长的偏好" * 10,
            strength=0.9,
        )
        for index in range(1, 4)
    ]
    block = render_opening(memories, NOW, max_chars=60)
    assert len(block.text) <= 60
    assert len(block.selected) <= 1


def test_render_quote_uses_short_source_quote() -> None:
    line = render_memory_line(_memory(source_quote="我先看例子"))
    assert line == "你说过“我先看例子”"


def test_render_long_quote_falls_back_to_text() -> None:
    line = render_memory_line(
        _memory(text="先看例子再看定义", source_quote="很长" * 40)
    )
    assert line == "你说过先看例子再看定义"


def test_render_preference_and_feeling() -> None:
    assert render_memory_line(_memory(kind="preference", text="先看例子")) == (
        "你提过先看例子"
    )
    assert render_memory_line(_memory(kind="feeling", text="听到长定义会烦")) == (
        "你说过听到长定义会烦"
    )


def test_compose_preamble_joins_life_and_memory() -> None:
    text = compose_preamble("今天只做了一件小事", "先想起几件你说过的事：你提过先看例子。")
    assert text == (
        "今天只做了一件小事。先想起几件你说过的事：你提过先看例子。"
    )


def test_compose_preamble_drops_memory_when_over_budget() -> None:
    life = "小事" * 30  # 60 字
    memory = "记忆" * 160  # 320 字
    text = compose_preamble(life, memory, max_chars=360)
    assert text == f"{life}。"
    assert len(text) <= 360


def test_extract_clue_with_content() -> None:
    assert extract_clue("你还记得我之前说怕公式吗") == "怕公式"
    assert extract_clue("你还记得我之前说过喜欢怎么学吗") == "喜欢怎么学"
    assert extract_clue("帮我回忆一下我喜欢先看例子") == "一下喜欢先看例子"


def test_extract_clue_without_content_is_empty() -> None:
    assert extract_clue("你还记得吗") == ""
    assert extract_clue("我说过什么") == ""
    assert extract_clue("今天天气不错") == ""
