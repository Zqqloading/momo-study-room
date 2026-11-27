"""评分验收 harness：10 条标准答案、同档一致率、跳题行为。

不进入日常会话路径；不改人工档位、不改提示词。
用法：
  python -m core.eval_scoring --prepare --questions <questions.json> --out <dir>
  python -m core.eval_scoring --run --answers <answers.json> --out <dir> --mode real
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .scoring import build_score_messages, parse_score_result

BANDS = (
    ("0-39", 0, 39),
    ("40-69", 40, 69),
    ("70-89", 70, 89),
    ("90-100", 90, 100),
)


def band_of(score: int) -> str:
    for label, low, high in BANDS:
        if low <= score <= high:
            return label
    raise ValueError(f"分数越界：{score}")


def normalize_band(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"人工档位不合法：{value!r}")
    if isinstance(value, int):
        return band_of(value)
    text = str(value).strip()
    if text in {label for label, _, _ in BANDS}:
        return text
    raise ValueError(f"人工档位不合法：{value!r}")


def answer_template(questions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "question_id": item["question_id"],
            "question_type": item.get("question_type"),
            "question_text": item["question_text"],
            "reference_answer": item.get("reference_answer", ""),
            "rubric_json": item.get("rubric_json", {}),
            "source_excerpt": item.get("source_excerpt", ""),
            "answer": "",
            "human_band": "",
            "skipped": False,
        }
        for item in questions
    ]


def render_scoring_sheet(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# 评分验收标准答案模板",
        "",
        "每条答案先写人工档位：0-39 / 40-69 / 70-89 / 90-100；跳题把 skipped 设为 true。",
        "样本要求：3 条全对、3 条对一半、2 条跑题、2 条跳题，覆盖五型。",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        lines.extend(
            [
                f"## {index}. 题目 {row['question_id']}（{row.get('question_type')}）",
                "",
                f"- 题干：{row['question_text']}",
                f"- 参考答案：{row.get('reference_answer', '')}",
                f"- 材料摘录：{row.get('source_excerpt', '')}",
                "- 人工档位：____",
                "- 答案：____",
                "",
            ]
        )
    return "\n".join(lines)


async def run_acceptance(
    rows: Sequence[Mapping[str, Any]], scorer: Any
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for row in rows:
        question_id = row["question_id"]
        if row.get("skipped"):
            results.append(
                {
                    "question_id": question_id,
                    "skipped": True,
                    "score": None,
                    "model_band": None,
                    "human_band": None,
                    "consistent": None,
                    "calls": 0,
                    "why": "",
                }
            )
            continue

        question = {
            "id": question_id,
            "question_text": row["question_text"],
            "question_type": row.get("question_type"),
            "source_excerpt": row.get("source_excerpt", ""),
            "rubric_json": row.get("rubric_json", {}),
        }
        answer = str(row.get("answer") or "")
        score: int | None = None
        why = ""
        calls = 0
        for _ in range(2):
            calls += 1
            try:
                raw = await scorer.grade(*build_score_messages(question, answer))
                parsed = parse_score_result(raw, expected_ids=[str(question_id)])
                score = parsed.questions[0].score
                why = parsed.questions[0].why
                break
            except Exception:
                continue

        human_band = normalize_band(row.get("human_band"))
        model_band = band_of(score) if score is not None else None
        results.append(
            {
                "question_id": question_id,
                "skipped": False,
                "score": score,
                "model_band": model_band,
                "human_band": human_band,
                "consistent": model_band == human_band,
                "calls": calls,
                "why": why,
            }
        )

    answered = [item for item in results if not item["skipped"]]
    skipped = [item for item in results if item["skipped"]]
    consistent = sum(1 for item in answered if item["consistent"])
    need = math.ceil(len(answered) * 0.75)
    skipped_ok = sum(1 for item in skipped if item["score"] is None and item["calls"] == 0)
    passed = (
        len(results) == 10
        and len(answered) == 8
        and len(skipped) == 2
        and consistent >= need
        and skipped_ok == len(skipped)
    )
    return {
        "total": len(results),
        "answered": len(answered),
        "skipped": len(skipped),
        "consistent": consistent,
        "needed": need,
        "skipped_ok": skipped_ok,
        "passed": passed,
        "results": results,
    }


def render_report(report: Mapping[str, Any]) -> str:
    lines = [
        "# 评分验收报告",
        "",
        f"- 样本：{report['total']} 条（已答 {report['answered']}，跳题 {report['skipped']}）",
        f"- 同档一致：{report['consistent']}/{report['answered']}（门槛 {report['needed']}）",
        f"- 跳题不评分：{report['skipped_ok']}/{report['skipped']}",
        f"- 结论：{'通过' if report['passed'] else '不通过'}",
        "",
        "| 题 | 人工档 | 模型分 | 模型档 | 一致 |",
        "|---|---|---|---|---|",
    ]
    for item in report["results"]:
        if item["skipped"]:
            lines.append(
                f"| {item['question_id']} | 跳题 | - | - | 不评分 |"
            )
        else:
            lines.append(
                f"| {item['question_id']} | {item['human_band']} | "
                f"{item['score'] if item['score'] is not None else '未评分'} | "
                f"{item['model_band'] or '-'} | "
                f"{'是' if item['consistent'] else '否'} |"
            )
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="评分验收 harness")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--questions", default="")
    parser.add_argument("--answers", default="")
    parser.add_argument("--out", default="docs/designs/review-20261125")
    parser.add_argument("--mode", choices=("real", "fake"), default=None)
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    if args.prepare:
        if not args.questions:
            print("--prepare 需要 --questions")
            return 1
        questions = json.loads(
            Path(args.questions).read_text(encoding="utf-8")
        )
        rows = answer_template(questions)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "answer-template.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (out_dir / "scoring-sheet.md").write_text(
            render_scoring_sheet(rows), encoding="utf-8"
        )
        print(f"已导出 {len(rows)} 条标准答案模板到 {out_dir}")
        return 0

    if args.run:
        if not args.answers:
            print("--run 需要 --answers")
            return 1
        rows = json.loads(Path(args.answers).read_text(encoding="utf-8"))

        from bff.config import load_settings
        from bff.providers.registry import build_providers

        settings = load_settings()
        if args.mode:
            settings = replace(settings, mode=args.mode)

        async def run() -> dict[str, Any]:
            providers = build_providers(settings)
            try:
                return await run_acceptance(rows, providers.scorer)
            finally:
                await providers.aclose()

        report = asyncio.run(run())
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "scoring-results.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (out_dir / "scoring-acceptance.md").write_text(
            render_report(report), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
