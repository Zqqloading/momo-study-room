"""提示词块与唯一拼装顺序。

所有对话面都走 ``compose_system_prompt``，避免 free talk / agent 各自
按不同顺序拼人设、语气、记忆和纪律。``data`` 只放 agent 工单 JSON，
永远最后。
"""

from __future__ import annotations

from dataclasses import dataclass

BLOCK_ORDER = (
    "role",
    "persona",
    "tone",
    "memory",
    "task",
    "context",
    "discipline",
    "data",
)


@dataclass(frozen=True, slots=True)
class PromptBlocks:
    role: str = ""
    persona: str = ""
    tone: str = ""
    memory: str = ""
    task: str = ""
    context: str = ""
    discipline: str = ""
    data: str = ""


def compose_system_prompt(blocks: PromptBlocks) -> str:
    parts = []
    for name in BLOCK_ORDER:
        value = getattr(blocks, name)
        if value and value.strip():
            parts.append(value.strip())
    return "\n\n".join(parts)


def tone_block(hint: str) -> str:
    hint = (hint or "").strip()
    if not hint:
        return ""
    return (
        f"【当前语气】\n{hint}\n"
        "（只影响语气，不影响教学规则；和人设/底线冲突时以底线为准。）"
    )


def memory_block(context: str) -> str:
    context = (context or "").strip()
    if not context:
        return ""
    return (
        "【用户要求回忆】\n"
        "用户问你是否记得以下内容。只依据这些记忆回答；没有就说没印象，不要编造。\n"
        f"{context}"
    )
