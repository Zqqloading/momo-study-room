"""出题验收 harness：导出盲评表、计算人工标签通过率。

不进入日常会话路径；不改提示词、不改人工标签。
用法：
  python -m core.eval_questions --prepare --out docs/designs/review-<日期>
  python -m core.eval_questions --score --labels <labels.json>
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .concepts import Concept, load_concepts
from .db import connect, init_schema
from .planner import Planner
from .question_generation import build_session_plan
from .store import Store

TYPE_DEFINITIONS = """\
- `concept` 概念理解：问为什么需要、解决什么业务问题、不用会怎样、与相邻概念的区别；不是“X 是什么”。
- `business` 业务运用：给具体业务场景，问怎么用、先做什么、产出什么、怎么判断有效。
- `tradeoff` 取舍权衡：给 A/B 或两种做法，问选哪个、放弃什么、什么条件下反转。
- `cost_risk` 成本风险：问成本、风险、谁承担、怎么兜底，至少两项。
- `synthesis` 综合判断：给完整场景与约束，要求做决策、说依据、说边界或失败信号。"""

_YES = {"理解", "understand", "yes", "ok", "对", "可", "业务", "business"}


def blind_rows(questions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """盲评只看题干 + 摘录 + 题型定义；隐藏声称题型与 rubric。"""
    return [
        {
            "question_id": item["question_id"],
            "question_text": item["question_text"],
            "source_excerpt": item["source_excerpt"],
        }
        for item in questions
    ]


def labels_template(questions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "question_id": item["question_id"],
            "question_type": "",
            "understanding": "",
            "perspective": "",
            "source": "",
        }
        for item in questions
    ]


def render_blind_markdown(questions: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# 出题盲评表",
        "",
        "只看题干、材料摘录与题型定义；不要看模型声称的题型或 rubric。",
        "逐题填写：题型（五型之一）、理解（理解/背诵）、视角（业务/程序）、溯源（可/不可）。",
        "",
        "## 题型定义",
        "",
        TYPE_DEFINITIONS,
        "",
        "## 待评题目",
        "",
    ]
    for index, item in enumerate(blind_rows(questions), start=1):
        lines.extend(
            [
                f"### {index}. 题目 id {item['question_id']}",
                "",
                f"- 题干：{item['question_text']}",
                f"- 材料摘录：{item['source_excerpt']}",
                "- 题型：____",
                "- 理解：____",
                "- 视角：____",
                "- 溯源：____",
                "",
            ]
        )
    return "\n".join(lines)


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def evaluate_question_labels(
    questions: Sequence[Mapping[str, Any]],
    labels: Sequence[Mapping[str, Any]],
    *,
    threshold: float = 0.8,
) -> dict[str, Any]:
    """比较人工标签与声称题型，输出四项通过率与总判定。"""
    claimed = {item["question_id"]: item["question_type"] for item in questions}
    by_id = {item["question_id"]: item for item in labels}
    missing = sorted(set(claimed) - set(by_id))
    if missing:
        raise ValueError(f"缺少标签：{missing}")

    counts = {"type": 0, "understanding": 0, "perspective": 0, "source": 0}
    failures: list[dict[str, Any]] = []
    for question_id, expected_type in claimed.items():
        label = by_id[question_id]
        reviewer_type = _normalize(label.get("question_type"))
        understanding = _normalize(label.get("understanding")) in _YES
        perspective = _normalize(label.get("perspective")) in _YES
        source = _normalize(label.get("source")) in _YES
        type_ok = reviewer_type == str(expected_type).lower()
        counts["type"] += int(type_ok)
        counts["understanding"] += int(understanding)
        counts["perspective"] += int(perspective)
        counts["source"] += int(source)
        if not all((type_ok, understanding, perspective, source)):
            failures.append(
                {
                    "question_id": question_id,
                    "claimed_type": expected_type,
                    "reviewer_type": reviewer_type,
                    "understanding": understanding,
                    "perspective": perspective,
                    "source": source,
                }
            )

    total = len(claimed)
    rates = {key: value / total if total else 0.0 for key, value in counts.items()}
    passed = (
        total == 10
        and rates["type"] >= threshold
        and rates["understanding"] >= threshold
        and rates["perspective"] == 1.0
        and rates["source"] == 1.0
    )
    return {
        "total": total,
        "counts": counts,
        "rates": rates,
        "thresholds": {
            "type": f">={int(threshold * 100)}%",
            "understanding": f">={int(threshold * 100)}%",
            "perspective": "100%",
            "source": "100%",
        },
        "passed": passed,
        "failures": failures,
    }


def render_report(report: Mapping[str, Any]) -> str:
    counts = report["counts"]
    total = report["total"]
    lines = [
        "# 出题验收报告",
        "",
        f"- 样本：{total} 题",
        f"- 题型：{counts['type']}/{total}",
        f"- 理解：{counts['understanding']}/{total}",
        f"- 业务视角：{counts['perspective']}/{total}",
        f"- 溯源：{counts['source']}/{total}",
        f"- 结论：{'通过' if report['passed'] else '不通过'}",
        "",
    ]
    if report["failures"]:
        lines.append("## 未通过项")
        lines.append("")
        for item in report["failures"]:
            lines.append(
                f"- 题目 {item['question_id']}：声称 {item['claimed_type']}，"
                f"人工 {item['reviewer_type']}；理解={item['understanding']}，"
                f"视角={item['perspective']}，溯源={item['source']}"
            )
        lines.append("")
    return "\n".join(lines)


def pick_concepts(
    store: Store, concepts: Sequence[Concept], *, limit: int
) -> list[Concept]:
    states = {state.id: state for state in store.concept_states()}
    by_id = {concept.id: concept for concept in concepts}
    planner = Planner(list(concepts))
    candidates = [
        state
        for state in states.values()
        if state.status == "active"
        and state.id in by_id
        and planner.unlocked(state.id, states)
    ]
    candidates.sort(
        key=lambda state: (
            by_id[state.id].difficulty,
            state.last_seen or "",
            state.id,
        )
    )
    return [by_id[state.id] for state in candidates[:limit]]


async def _generate(
    store: Store, concepts: Sequence[Concept]
) -> list[dict[str, Any]]:
    from bff.config import load_settings
    from bff.providers.registry import build_providers
    from bff.question_generation import BffQuestionGenerator

    settings = load_settings()
    providers = build_providers(settings)
    generator = BffQuestionGenerator(
        store,
        providers.embedder,
        providers.scorer,
        model=settings.scorer.model or "deepseek-chat",
    )
    payload: list[dict[str, Any]] = []
    try:
        for concept in concepts:
            plan = build_session_plan(
                main_concept=concept, review_concept=None
            )
            generated = await generator.generate(plan)
            for item in generated.questions:
                payload.append(
                    {
                        "question_id": f"{concept.id}-{item.slot}",
                        "concept_id": item.concept_id,
                        "question_type": item.question_type,
                        "question_text": item.question_text,
                        "reference_answer": item.reference_answer,
                        "rubric_json": item.rubric,
                        "source_chunk_id": item.source_chunk_id,
                        "source_url": item.source_url,
                        "source_excerpt": item.source_excerpt,
                        "generation_meta": generated.meta,
                    }
                )
    finally:
        await providers.aclose()
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="出题验收 harness")
    parser.add_argument("--prepare", action="store_true", help="生成 2 场并导出盲评表")
    parser.add_argument("--score", action="store_true", help="读人工标签并计算通过率")
    parser.add_argument("--db", default="data/app-v5.db")
    parser.add_argument("--concepts", default="concepts.yaml")
    parser.add_argument("--sessions", type=int, default=2)
    parser.add_argument("--out", default="docs/designs/review-20261125")
    parser.add_argument("--labels", default="")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    if args.prepare:
        concepts = load_concepts(args.concepts)
        store = Store(connect(args.db))
        try:
            init_schema(store.conn)
            picked = pick_concepts(store, concepts, limit=args.sessions)
            if len(picked) < args.sessions:
                print(f"可出概念不足：需要 {args.sessions}，只有 {len(picked)}")
                return 1
            questions = asyncio.run(_generate(store, picked))
        finally:
            store.close()

        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "questions.json").write_text(
            json.dumps(questions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out_dir / "blind-review.md").write_text(
            render_blind_markdown(questions), encoding="utf-8"
        )
        (out_dir / "labels-template.json").write_text(
            json.dumps(
                labels_template(questions), ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        print(f"已导出 {len(questions)} 题到 {out_dir}")
        return 0

    if args.score:
        if not args.labels:
            print("--score 需要 --labels")
            return 1
        questions = json.loads(
            (out_dir / "questions.json").read_text(encoding="utf-8")
        )
        labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
        report = evaluate_question_labels(questions, labels)
        (out_dir / "question-acceptance.md").write_text(
            render_report(report), encoding="utf-8"
        )
        (out_dir / "question-acceptance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
