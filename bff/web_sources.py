"""网页搜索结果：预过滤、域名/日期归一化与来源合并。"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from core.ports import SearchHit
from core.retrieval import RetrievedChunk
from core.router import WEB_TRIGGER_WORDS

from .retrieval import sources_payload

WEB_RESULT_LIMIT = 3
MIN_CONTENT_CHARS = 80

WEB_STOPWORDS = frozenset(
    {
        *WEB_TRIGGER_WORDS,
        "这个",
        "那个",
        "这些",
        "那些",
        "哪些",
        "哪个",
        "哪里",
        "什么是",
        "是什么",
        "什么",
        "为什么",
        "怎么",
        "如何",
        "什么时候",
        "可以",
        "没有",
        "不存在",
        "是不是",
        "能不能",
        "可不可以",
        "帮我",
        "一下",
        "请问",
        "词条",
    }
)


def filter_web_results(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    """content 预过滤：非空、足够长、与 query 的实义词项重叠、URL 去重。"""
    terms = _content_terms(query)
    if not terms:
        return []

    selected: list[SearchHit] = []
    seen: set[str] = set()
    for hit in sorted(hits, key=lambda item: item.score, reverse=True):
        content = hit.content.strip()
        if len(content) < MIN_CONTENT_CHARS:
            continue
        key = hit.url.split("#", 1)[0]
        if key in seen:
            continue
        if not any(term in content for term in terms):
            continue
        seen.add(key)
        selected.append(hit)
        if len(selected) >= WEB_RESULT_LIMIT:
            break
    return selected


def _content_terms(query: str) -> set[str]:
    """删除停用词后再取词项；中文展开 2-gram。"""
    cleaned = query
    for word in sorted(WEB_STOPWORDS, key=len, reverse=True):
        cleaned = cleaned.replace(word, " ")
    tokens = [token for token in re.split(r"\W+", cleaned) if len(token) >= 2]
    terms: set[str] = set(tokens)
    for token in tokens:
        if any("\u4e00" <= char <= "\u9fff" for char in token):
            terms.update(token[index : index + 2] for index in range(len(token) - 1))
    return terms


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def web_sources_payload(
    hits: list[SearchHit], *, start_index: int, retrieved_at: str
) -> list[dict[str, object]]:
    return [
        {
            "index": start_index + offset,
            "title": hit.title or domain_of(hit.url) or "网页",
            "url": hit.url,
            "domain": domain_of(hit.url),
            "excerpt": _excerpt(hit.content, 160),
            "kind": "web",
            "published_at": hit.published_at,
            "retrieved_at": retrieved_at,
        }
        for offset, hit in enumerate(hits)
    ]


def web_context_items(
    hits: list[SearchHit], *, start_index: int, retrieved_at: str
) -> list[dict[str, object]]:
    return [
        {
            "index": start_index + offset,
            "title": hit.title or domain_of(hit.url) or "网页",
            "domain": domain_of(hit.url),
            "content": hit.content,
            "published_at": hit.published_at,
            "retrieved_at": retrieved_at,
        }
        for offset, hit in enumerate(hits)
    ]


def merge_sources(
    local_hits: list[RetrievedChunk],
    web_hits: list[SearchHit],
    *,
    retrieved_at: str,
) -> list[dict[str, object]]:
    local = sources_payload(local_hits)
    web = web_sources_payload(
        web_hits, start_index=len(local) + 1, retrieved_at=retrieved_at
    )
    return local + web


def _excerpt(text: str, max_chars: int) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:max_chars].rstrip()
