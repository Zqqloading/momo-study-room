from __future__ import annotations

import asyncio

from bff.providers.fake import FakeSearch, NullSearch
from core.free_talk import build_free_talk_messages, format_web_context
from core.ports import SearchHit
from core.retrieval import RetrievedChunk
from bff.web_sources import (
    filter_web_results,
    merge_sources,
    web_context_items,
    web_sources_payload,
)


def test_search_provider_contract() -> None:
    hits = asyncio.run(FakeSearch().search("agent"))
    assert hits
    assert isinstance(hits[0], SearchHit)
    assert asyncio.run(NullSearch().search("agent")) == []


def hit(
    url: str,
    content: str,
    *,
    title: str = "标题",
    score: float = 0.8,
    published_at: str | None = "2026-11-20",
) -> SearchHit:
    return SearchHit(
        title=title,
        url=url,
        content=content,
        score=score,
        published_at=published_at,
    )


def test_filter_web_results_drops_short_empty_and_unrelated() -> None:
    query = "最新 agent 版本"
    hits = [
        hit("https://a.example/1", "agent " + "正文" * 60),
        hit("https://a.example/2", ""),
        hit("https://a.example/3", "太短"),
        hit("https://a.example/4", "完全无关的天气内容" * 20),
    ]
    selected = filter_web_results(query, hits)
    assert [item.url for item in selected] == ["https://a.example/1"]


def test_filter_web_results_rejects_query_without_terms() -> None:
    hits = [hit("https://a.example/1", "正文" * 50)]
    assert filter_web_results("a", hits) == []
    assert filter_web_results("这个词条是什么", hits) == []


def test_filter_web_results_drops_stopword_only_overlap() -> None:
    query = "联网查一下 zzqqxxjj9876543210 这个词条是什么"
    junk = [
        hit("https://a.example/1", "这个词条不存在，我也没有相关信息。" * 10),
        hit("https://a.example/2", "联网搜索可以帮助你找到答案。" * 10),
    ]
    assert filter_web_results(query, junk) == []


def test_filter_web_results_keeps_content_overlap() -> None:
    query = "联网查一下 区块链 是什么"
    good = [hit("https://a.example/1", "区块链是一种分布式账本。" * 10)]
    assert len(filter_web_results(query, good)) == 1


def test_filter_web_results_dedupes_and_caps_three() -> None:
    query = "agent"
    hits = [
        hit(f"https://a.example/{index}", "agent " + "正文" * 60, score=1.0 - index * 0.1)
        for index in range(5)
    ]
    hits.append(hit("https://a.example/0#section", "agent " + "正文" * 60, score=0.99))
    selected = filter_web_results(query, hits)
    assert len(selected) == 3
    assert selected[0].url == "https://a.example/0"


def test_web_sources_payload_has_domain_and_dates() -> None:
    hits = [hit("https://www.example.com/a", "agent " + "正文" * 60)]
    payload = web_sources_payload(hits, start_index=2, retrieved_at="2026-11-24")
    assert payload[0]["index"] == 2
    assert payload[0]["domain"] == "example.com"
    assert payload[0]["kind"] == "web"
    assert payload[0]["published_at"] == "2026-11-20"
    assert payload[0]["retrieved_at"] == "2026-11-24"


def test_merge_sources_puts_material_before_web() -> None:
    local = [
        RetrievedChunk(
            concept_id="c1",
            text="材料",
            source_excerpt="摘录",
            source_url="local://materials/m.md",
            score=0.1,
            fts_hit=True,
        )
    ]
    web = [hit("https://example.com/a", "agent " + "正文" * 60)]
    sources = merge_sources(local, web, retrieved_at="2026-11-24")
    assert [item["index"] for item in sources] == [1, 2]
    assert [item["kind"] for item in sources] == ["material", "web"]
    assert sources[0]["domain"] == ""
    assert sources[0]["published_at"] is None
    assert sources[0]["retrieved_at"] is None


def test_format_web_context_shows_date_or_unknown_and_truncates() -> None:
    items = web_context_items(
        [hit("https://example.com/a", "agent " + "正文" * 500, published_at=None)],
        start_index=1,
        retrieved_at="2026-11-24",
    )
    context = format_web_context(items)
    assert "[1]" in context
    assert "example.com" in context
    assert "未标注日期" in context
    assert "…" in context


def test_web_prompt_material_first_and_conflict() -> None:
    messages = build_free_talk_messages(
        [],
        "最新 agent 版本",
        "teach",
        material_context="[1] 材料",
        web_context="[2] 网页",
        grounded=True,
        web_status="ok",
    )
    assert "材料摘录是已核实内容" in messages[0].content
    assert "材料说 X，网上有来源说 Y" in messages[0].content
    assert "网上信息，可能变化" in messages[0].content


def test_web_prompt_only_web_when_local_missing() -> None:
    messages = build_free_talk_messages(
        [],
        "最新 agent 版本",
        "teach",
        web_context="[1] 网页",
        grounded=False,
        web_status="ok",
    )
    assert "只依据网络检索" in messages[0].content
    assert "这是网上信息，可能变化" in messages[0].content


def test_web_prompt_distinguishes_empty_and_failed() -> None:
    empty = build_free_talk_messages(
        [], "最新 agent 版本", "teach", grounded=False, web_status="empty"
    )
    failed = build_free_talk_messages(
        [], "最新 agent 版本", "teach", grounded=False, web_status="failed"
    )
    assert "联网也没查到" in empty[0].content
    assert "联网搜索暂时不可用" in failed[0].content
