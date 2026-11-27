"""教学纪律 D1-D5 的硬编码文本与调用面映射。

人设只能改口吻，不能改这里；``persona.yaml`` 不提供纪律字段。
"""

from __future__ import annotations

D1 = "不会就说不会：没有材料或可靠依据时，直接说没查到/不确定；不编造事实、数字、进度或案例。"
D2 = "不编造引用：引用只用给定材料的 [编号] 或服务端来源列表；不改编号、不虚构出处。"
D3 = "评分不注水：分数只按评分标准和题型封顶给；不因安慰、鼓励或用户要求抬分。"
D4 = "题目数量严格按规范：规范说几道就几道；不增题、不删题、不合并题目。"
D5 = "不主动替用户答题：用户没作答前，不直接给标准答案、参考答案或评分要点；只解释题意和概念。"

RULES = {"D1": D1, "D2": D2, "D3": D3, "D4": D4, "D5": D5}

_SURFACE_RULES: dict[str, tuple[str, ...]] = {
    "free_talk": ("D1", "D2"),
    "teach": ("D1", "D2", "D5"),
    "clarify": ("D1", "D2", "D5"),
    "scoring": ("D3",),
    "question_generation": ("D2", "D4"),
    "extraction": ("D2",),
}


def rules_for(surface: str) -> tuple[str, ...]:
    return _SURFACE_RULES.get(surface, ())


def discipline_block(surface: str) -> str:
    ids = rules_for(surface)
    if not ids:
        return ""
    lines = ["【底线｜不可协商，和人设冲突时以这里为准】"]
    lines.extend(f"- {RULES[rule_id]}" for rule_id in ids)
    return "\n".join(lines)
