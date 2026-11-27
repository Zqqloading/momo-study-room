from __future__ import annotations

from core.tts_text import split_for_tts


def test_splits_on_strong_punctuation() -> None:
    assert split_for_tts("第一句。第二句！第三句？") == [
        "第一句。",
        "第二句！",
        "第三句？",
    ]


def test_merges_short_clauses_up_to_limit() -> None:
    text = "这是很长的一句话，里面有逗号分开的短句，也有更短的句子，需要合并到接近上限。"
    chunks = split_for_tts(text, max_chars=20)
    assert all(len(chunk) <= 20 for chunk in chunks)
    assert "".join(chunks) == text


def test_hard_splits_overlong_clause() -> None:
    text = "无标点" * 30
    chunks = split_for_tts(text, max_chars=10)
    assert all(len(chunk) <= 10 for chunk in chunks)
    assert "".join(chunks) == text


def test_empty_text_returns_no_chunks() -> None:
    assert split_for_tts("") == []
    assert split_for_tts("   ") == []


def test_keeps_single_short_sentence_intact() -> None:
    assert split_for_tts("先说一下今天学什么。") == ["先说一下今天学什么。"]
