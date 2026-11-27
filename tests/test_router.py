from __future__ import annotations

from core.router import (
    classify,
    classify_free_talk,
    explicit_web_request,
    is_mixed,
    is_suspicious,
    needs_web,
    search_query,
    time_sensitive,
)


def test_exact_whitelist_routes_dont_know() -> None:
    assert classify("不知道") == "dont_know"
    assert classify(" 我不知道。") == "dont_know"
    assert classify("不太知道！") == "dont_know"


def test_exact_whitelist_routes_knows() -> None:
    assert classify("知道了") == "knows"
    assert classify("明白了！") == "knows"
    assert classify("会了") == "knows"


def test_long_sentence_is_an_answer() -> None:
    assert classify("不知道，因为 agent 的循环我还没弄懂") == "answer"
    assert classify("我觉得知道了") == "answer"
    assert classify("agent 就是会自己决定下一步") == "answer"


def test_suspicious_transcript() -> None:
    assert is_suspicious("") is True
    assert is_suspicious("嗯") is True
    assert is_suspicious("嗯嗯嗯") is True
    assert is_suspicious("。。。") is True
    assert is_suspicious("agent 循环") is False


def test_whitelist_is_not_suspicious() -> None:
    assert is_suspicious("不知道") is False
    assert is_suspicious("知道了") is False


def test_mixed_sentence_detection() -> None:
    assert is_mixed("agent 循环是什么？") is True
    assert is_mixed("为什么这里要观察两次") is True
    assert is_mixed("知道了") is False
    assert is_mixed("观察、决策、行动") is False


def test_free_talk_learning_questions_route_to_teach() -> None:
    assert classify_free_talk("什么是 agent 循环") == "teach"
    assert classify_free_talk("为什么需要记忆") == "teach"
    assert classify_free_talk("解释一下工具调用") == "teach"


def test_free_talk_small_talk_routes_to_chat() -> None:
    assert classify_free_talk("今天好累") == "chat"
    assert classify_free_talk("你好呀") == "chat"


def test_explicit_web_request() -> None:
    assert explicit_web_request("联网查一下 agent") is True
    assert explicit_web_request("搜索一下最新版本") is True
    assert explicit_web_request("什么是 agent") is False


def test_time_sensitive_keywords() -> None:
    assert time_sensitive("最新的 agent 版本") is True
    assert time_sensitive("今天 agent 圈有什么新闻") is True
    assert time_sensitive("agent 是什么") is False


def test_needs_web_covers_explicit_and_time() -> None:
    assert needs_web("联网查一下 agent") is True
    assert needs_web("最新 agent 版本") is True
    assert needs_web("什么是 agent") is False
    assert needs_web("") is False


def test_search_query_appends_year_month_only_for_time_questions() -> None:
    assert search_query("最新 agent 版本", today="2026-11-24") == (
        "最新 agent 版本 2026年11月"
    )
    assert search_query("什么是 agent", today="2026-11-24") == "什么是 agent"


def test_search_query_strips_web_triggers() -> None:
    assert search_query("联网查一下 agent", today="2026-11-24") == "agent"
    assert search_query("联网 查一下 agent", today="2026-11-24") == "agent"
    assert search_query("搜索一下最新版本", today="2026-11-24") == (
        "最新版本 2026年11月"
    )
    assert search_query("联网查一下", today="2026-11-24") == ""
    assert search_query("？", today="2026-11-24") == ""
