"""会话外的自由对话：教学讲解与闲聊两种提示词。

不写数据库、不评分；只拼消息，历史窗口按连接保存在 BFF。
系统提示统一走 ``core.prompt.compose_system_prompt``。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .discipline import discipline_block
from .persona import role_line
from .ports import ChatMessage
from .prompt import PromptBlocks, compose_system_prompt, memory_block, tone_block

MAX_HISTORY_MESSAGES = 12
MATERIAL_MAX_CHARS = 800
WEB_MAX_CHARS = 800
NO_MATERIAL_PREFIX = "材料里没有直接讲到。"

TEACH_TASK = """用户问了一个概念或学习问题：用不超过 100 字正面解释，给一个人话定义或生活例子。
解释完可以追问一句，请对方用自己的话说一遍；不要只反问开场。
不要说黑话，不要评分。用中文回答。"""

CHAT_TASK = """用不超过 60 字自然回应；
可以追问一句，但不要长篇大论，不要评分。用中文回答。"""


def format_progress(
    concepts: list[tuple[str, int, str | None]],
    sessions: list[tuple[str, str, str, float | None]],
) -> str:
    """把当前进度压成一段短文本，注入系统提示。

    concepts: (名字, mastery, review_due_at)
    sessions: (date, kind, status, session_score)
    """
    lines: list[str] = []
    for name, mastery, due in concepts[:5]:
        suffix = f"，{due} 复习" if due else ""
        lines.append(f"- {name}：mastery {mastery}{suffix}")
    if sessions:
        recent = "；".join(
            f"{date} {kind} {status}"
            + (f" {score:g} 分" if score is not None else "")
            for date, kind, status, score in sessions[:3]
        )
        lines.append(f"最近会话：{recent}")
    if not lines:
        return ""
    return "当前学习进度：\n" + "\n".join(lines)


def format_material_context(items: Sequence[Mapping[str, Any]]) -> str:
    """把检索结果压成提示词里的材料段；父块过长时截断。"""
    if not items:
        return ""
    lines = ["材料摘录（只依据这些内容回答；引用时用 [编号]）："]
    for index, item in enumerate(items, start=1):
        text = " ".join(str(item.get("text") or "").split())
        if len(text) > MATERIAL_MAX_CHARS:
            text = text[:MATERIAL_MAX_CHARS].rstrip() + "…"
        lines.append(f"[{item.get('index', index)}] {text}")
        excerpt = " ".join(str(item.get("excerpt") or "").split())
        if excerpt and excerpt not in text:
            lines.append(f"    出处摘录：{excerpt}")
    return "\n".join(lines)


def format_web_context(items: Sequence[Mapping[str, Any]]) -> str:
    """把网页搜索结果压成提示词里的网络检索段。"""
    if not items:
        return ""
    lines = ["网络检索（未核实时效内容；引用时用 [编号]）："]
    for index, item in enumerate(items, start=1):
        published = item.get("published_at") or "未标注日期"
        lines.append(
            f"[{item.get('index', index)}] {item.get('title') or '网页'}"
            f"（{item.get('domain') or '未知域名'} · {published} · "
            f"检索于 {item.get('retrieved_at') or '今天'}）"
        )
        text = " ".join(str(item.get("content") or "").split())
        if len(text) > WEB_MAX_CHARS:
            text = text[:WEB_MAX_CHARS].rstrip() + "…"
        lines.append(text)
    return "\n".join(lines)


def _grounding_note(
    mode: str,
    *,
    grounded: bool | None,
    web_status: str | None,
    web_context: str,
) -> str:
    web_ok = web_status == "ok" and bool(web_context.strip())
    if grounded is True and web_ok:
        return (
            "材料摘录是已核实内容，网络检索是未核实时效内容。"
            "先依据材料；网页只作补充；两者冲突时明确说“材料说 X，网上有来源说 Y”，"
            "不要用网页覆盖材料。回答 1–3 句口语化，引用用 [编号]，"
            "并提示“网上信息，可能变化”。"
        )
    if grounded is True:
        return (
            "只依据材料摘录回答；引用时用 [编号]；"
            "不要编造摘录里没有的出处。"
        )
    if grounded is False and web_ok:
        return (
            "材料里没有直接相关的内容，但网络检索已经查到了结果；"
            "先说明“网上查到了”，再只依据网络检索回答。"
            "回答 1–3 句口语化，引用用 [编号]，并明确说“这是网上信息，可能变化”；"
            "不要冒充材料内容。"
        )
    if grounded is False and web_status == "empty":
        return (
            "材料里没有，联网也没查到。不要编造具体事实；"
            "不要重复兜底文案，服务端会加。"
        )
    if grounded is False and web_status == "failed":
        return (
            "材料里没有，联网搜索暂时不可用。不要编造具体事实；"
            "不要重复兜底文案，服务端会加。"
        )
    if grounded is False and mode == "teach":
        return (
            "材料里没有检索到直接相关的内容。不要编造具体事实；"
            "不要重复兜底文案，服务端会加；如果继续用一般知识解释，"
            "必须标注“这不是材料内容”。"
        )
    if grounded is False:
        return (
            "如果用户问的是学习问题但材料里没有，不要编造；"
            "服务端会加兜底说明；闲聊不必提材料。"
        )
    return ""


def build_free_talk_messages(
    history: Sequence[ChatMessage],
    text: str,
    mode: str,
    progress: str = "",
    material_context: str = "",
    web_context: str = "",
    *,
    grounded: bool | None = None,
    web_status: str | None = None,
    persona_block: str = "",
    tone_hint: str = "",
    memory_context: str = "",
) -> list[ChatMessage]:
    context_parts: list[str] = []
    if progress.strip():
        context_parts.append(
            f"{progress.strip()}\n（只作背景，不要逐条复述。）"
        )
    if material_context.strip():
        context_parts.append(material_context.strip())
    if web_context.strip():
        context_parts.append(web_context.strip())
    grounding = _grounding_note(
        mode,
        grounded=grounded,
        web_status=web_status,
        web_context=web_context,
    )
    if grounding:
        context_parts.append(grounding)

    system = compose_system_prompt(
        PromptBlocks(
            role=role_line(),
            persona=persona_block,
            tone=tone_block(tone_hint),
            memory=memory_block(memory_context),
            task=TEACH_TASK if mode == "teach" else CHAT_TASK,
            context="\n\n".join(context_parts),
            discipline=discipline_block(
                "teach" if mode == "teach" else "free_talk"
            ),
        )
    )
    previous = list(history)[-MAX_HISTORY_MESSAGES:]
    return [
        ChatMessage(role="system", content=system),
        *previous,
        ChatMessage(role="user", content=text),
    ]
