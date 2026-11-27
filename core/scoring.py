"""评分契约的解析与校验（冻结规格"评分契约"一节）。

模型输出是不可信文本：可能带 ```json 围栏、前后废话、越界分数、漏题。
这里只做确定性校验，不重试、不补分；重试一次与 unscored 的编排在 BFF/v0。

五档 rubric 仅作文档，评分本身由模型给 0-100。
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from .ports import QuestionScore, ScoreResult, SessionMisconception

# 嵌进评分提示词里，告诉模型必须返回什么形状。
SCORE_SCHEMA_HINT = """只返回一个 JSON 对象，不要 Markdown 围栏，不要解释：
{
  "questions": [
    {"id": "<题目 id>", "score": 0, "why": "<一句为什么>",
     "reference_answer": "<一句标准答案>",
     "misconception_hit": false, "certain": false}
  ],
  "session_misconception": null
}
- score 是 0 到 100 的整数。
- 每题都要有，id 用给定的题目 id。
- reference_answer 是开放题的标准答案：先给结论，再给判断依据，最多 120 字，
  且必须是能独立读懂的完整句子（句末收住；宁可少写一层，也不要写到一半）；辨析题可为空字符串。
- misconception_hit 表示这题是否命中一个误解；certain 表示是否确定。
- session_misconception 至多一条：{"text": "...", "concept_key": "..."} 或 null；
  字符串或数组都算非法。
"""


_TYPE_LABELS = {
    "concept": "概念理解",
    "business": "业务运用",
    "tradeoff": "取舍权衡",
    "cost_risk": "成本风险",
    "synthesis": "综合判断",
}


SCORE_SYSTEM_PROMPT = (
    "你是 B 端 AI 产品的评分员。按题型判断业务/产品理解，不按关键词匹配。\n"
    "分档：\n"
    "- 0-30：空白、不知道、完全跑题、概念相反。\n"
    "- 40-65：提到正确名词或部分要点，但关系说错或不完整。\n"
    "- 70-89：方向对、要点基本齐全，但缺自己的例子、边界或具体动作。\n"
    "- 90-100：正确、能结合业务场景或例子，并说出边界、代价或反例。\n"
    "题型封顶：\n"
    "- 只背定义、只复述材料原句、没有业务后果或场景判断：最高 60。\n"
    "- 业务运用：没有具体动作或场景映射：最高 60。\n"
    "- 取舍权衡：没有明确选择、代价或反转条件：最高 69。\n"
    "- 成本风险：少于 2 项成本或风险，或无兜底：最高 69。\n"
    "- 综合判断：没有决策、依据或边界：最高 69。\n"
    "参考答案只作对照，不要求逐字；用户用自己的例子说清也算对。\n"
    "只泛泛说方向、没说具体机制或步骤的，最多 60，不要给 70 以上。\n"
    "评分要与 rubric 的具体要点对应，严格但不过度惩罚。\n"
    "反馈只评价答案，不评价用户本人；不讽刺、不贬低。"
)


def _rubric_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return raw if isinstance(raw, dict) else {}


def build_score_messages(question: Mapping[str, Any], answer: str) -> tuple[str, str]:
    """拼一次单题评分调用；question 是 session_questions 的一行。"""
    rubric = _rubric_object(question.get("rubric_json"))
    reference = str(
        rubric.get("reference_answer")
        or rubric.get("criteria")
        or rubric.get("explanation")
        or ""
    ).strip()

    lines: list[str] = []
    question_type = question.get("question_type")
    if question_type:
        label = _TYPE_LABELS.get(str(question_type), str(question_type))
        lines.append(f"题目类型：{question_type}（{label}）")
    lines.append(f"题目 id：{question['id']}")
    lines.append(f"题目：{question['question_text']}")
    excerpt = str(question.get("source_excerpt") or "").strip()
    if excerpt:
        lines.append(f"材料出处：{excerpt}")
    lines.append(f"评分标准：{question.get('rubric_json') or '{}'}")
    if reference:
        lines.append(f"参考答案：{reference}")
    lines.append(f"用户回答：{answer}")
    lines.append("")
    lines.append(SCORE_SCHEMA_HINT)
    return SCORE_SYSTEM_PROMPT, "\n".join(lines)


class ScoringError(ValueError):
    """评分输出无法按契约解析。调用方据此重试或记 unscored。"""


def extract_json_object(raw: str) -> dict[str, Any]:
    """从模型输出里抠出第一个 JSON 对象。容忍 ```json 围栏与前后闲话。"""
    text = raw.strip()
    if text.startswith("```"):
        # 去掉首行围栏与结尾围栏
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ScoringError(f"输出里没有 JSON 对象：{raw[:200]!r}") from None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ScoringError(f"JSON 解析失败：{exc}") from exc

    if not isinstance(parsed, dict):
        raise ScoringError("JSON 顶层必须是对象")
    return parsed


def _as_score(value: Any, question_id: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScoringError(f"题目 {question_id} 的 score 不是数字：{value!r}")
    score = int(value)
    if score != value:
        raise ScoringError(f"题目 {question_id} 的 score 必须是整数：{value!r}")
    if not 0 <= score <= 100:
        raise ScoringError(f"题目 {question_id} 的 score 越界：{score}")
    return score


def _as_bool(value: Any, field_name: str, question_id: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ScoringError(f"题目 {question_id} 的 {field_name} 不是布尔：{value!r}")


def _as_reference(value: Any, question_id: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ScoringError(f"题目 {question_id} 的 reference_answer 不是字符串：{value!r}")
    return value.strip()


def parse_score_result(raw: str, expected_ids: Sequence[str] | None = None) -> ScoreResult:
    """解析并校验一次评分输出。任何不合契约都抛 ``ScoringError``。"""
    payload = extract_json_object(raw)

    questions_raw = payload.get("questions")
    if not isinstance(questions_raw, list) or not questions_raw:
        raise ScoringError("questions 缺失或为空")

    questions: list[QuestionScore] = []
    seen: list[str] = []
    for item in questions_raw:
        if not isinstance(item, dict):
            raise ScoringError("questions 里有非对象元素")
        question_id = str(item.get("id", "")).strip()
        if not question_id:
            raise ScoringError("题目缺少 id")
        if question_id in seen:
            raise ScoringError(f"题目 id 重复：{question_id}")
        seen.append(question_id)

        why = item.get("why")
        if not isinstance(why, str) or not why.strip():
            raise ScoringError(f"题目 {question_id} 缺少 why")

        questions.append(
            QuestionScore(
                question_id=question_id,
                score=_as_score(item.get("score"), question_id),
                why=why.strip(),
                misconception_hit=_as_bool(
                    item.get("misconception_hit", False), "misconception_hit", question_id
                ),
                certain=_as_bool(item.get("certain", False), "certain", question_id),
                reference_answer=_as_reference(
                    item.get("reference_answer"), question_id
                ),
            )
        )

    if expected_ids is not None:
        expected = [str(i) for i in expected_ids]
        missing = [i for i in expected if i not in seen]
        extra = [i for i in seen if i not in expected]
        if missing:
            raise ScoringError(f"漏评分题：{missing}")
        if extra:
            raise ScoringError(f"多出未知题：{extra}")

    misconception: SessionMisconception | None = None
    raw_misconception = payload.get("session_misconception")
    if raw_misconception is not None:
        if not isinstance(raw_misconception, dict):
            raise ScoringError("session_misconception 必须是对象或 null")
        text = raw_misconception.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ScoringError("session_misconception.text 缺失")
        concept_key = raw_misconception.get("concept_key")
        misconception = SessionMisconception(
            text=text.strip(),
            concept_key=str(concept_key).strip() if concept_key else None,
        )

    return ScoreResult(questions=tuple(questions), session_misconception=misconception)
