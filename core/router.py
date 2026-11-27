"""最小路由：整句精确匹配，外加可疑转写与混合句判定。

长句一律按正常答案走评分；白名单只认整句，避免误吞真实回答。
"""

from __future__ import annotations

import re

DONT_KNOW = frozenset({"不知道", "不懂", "不会", "我不知道", "不太知道", "不清楚"})
KNOWS = frozenset({"知道了", "懂了", "明白了", "会了"})
_WHITELIST = DONT_KNOW | KNOWS

_PUNCTUATION = re.compile(r"[\s，。！？、,.!?;；:：\"'“”‘’（）()\[\]【】…—-]+")
_INTERJECTIONS = frozenset({"嗯", "啊", "哦", "呃", "唉", "噢", "诶", "嗯嗯", "哦哦", "啊啊"})
_QUESTION_WORDS = (
    "吗",
    "呢",
    "什么",
    "为什么",
    "怎么",
    "哪",
    "谁",
    "多少",
    "是不是",
    "能不能",
    "可不可以",
    "如何",
)

_LEARNING_HINTS = (
    "什么",
    "为什么",
    "怎么",
    "如何",
    "解释",
    "讲讲",
    "区别",
    "原理",
    "定义",
    "举例",
    "教我",
)

WEB_TRIGGER_WORDS = (
    "联网",
    "上网查",
    "搜索一下",
    "搜一下",
    "查一下",
)

_TIME_HINTS = (
    "最新",
    "最近",
    "今天",
    "现在",
    "当前",
    "目前",
    "新闻",
    "价格",
    "股价",
    "汇率",
    "发布",
    "上线",
    "更新",
    "版本",
    "谁",
    "什么时候",
    "哪年",
    "今年",
)


def _contains(text: str, words: tuple[str, ...]) -> bool:
    normalized = normalize(text)
    return any(word in normalized for word in words)


def explicit_web_request(text: str) -> bool:
    return _contains(text, WEB_TRIGGER_WORDS)


def time_sensitive(text: str) -> bool:
    return _contains(text, _TIME_HINTS)


def needs_web(text: str) -> bool:
    """显式联网要求或时效问题；不调模型。"""
    return explicit_web_request(text) or time_sensitive(text)


def search_query(text: str, *, today: str) -> str:
    """剥离联网触发词；时效问题追加当前年月；没有可检索内容时返回空串。"""
    stripped = text
    for word in sorted(WEB_TRIGGER_WORDS, key=len, reverse=True):
        stripped = stripped.replace(word, " ")
    stripped = " ".join(stripped.split())
    if not normalize(stripped):
        return ""
    if not time_sensitive(text):
        return stripped
    year = today[:4]
    month = today[5:7]
    try:
        month = str(int(month))
    except ValueError:
        pass
    return f"{stripped} {year}年{month}月"


def normalize(text: str) -> str:
    return _PUNCTUATION.sub("", text.strip())


def classify_free_talk(text: str) -> str:
    """会话外的自由对话：学习类问题走教学，其余走闲聊。"""
    normalized = normalize(text)
    if any(hint in normalized for hint in _LEARNING_HINTS):
        return "teach"
    return "chat"


def classify(text: str) -> str:
    """返回 dont_know / knows / answer。"""
    normalized = normalize(text)
    if normalized in DONT_KNOW:
        return "dont_know"
    if normalized in KNOWS:
        return "knows"
    return "answer"


def is_suspicious(text: str) -> bool:
    normalized = normalize(text)
    if not normalized:
        return True
    if normalized in _WHITELIST:
        return False
    if normalized in _INTERJECTIONS:
        return True
    if len(normalized) < 4:
        return True
    return len(set(normalized)) == 1


def is_mixed(text: str) -> bool:
    normalized = normalize(text)
    if not normalized or normalized in _WHITELIST:
        return False
    return any(word in normalized for word in _QUESTION_WORDS)
