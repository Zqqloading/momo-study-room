from __future__ import annotations

import asyncio
import json
import re

import pytest

from core.eval_scoring import (
    answer_template,
    band_of,
    render_report,
    render_scoring_sheet,
    run_acceptance,
)

TYPES = ("concept", "business", "tradeoff", "cost_risk", "synthesis")


class FakeScorer:
    def __init__(self, scores: list[int]) -> None:
        self.scores = list(scores)
        self.calls = 0

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        match = re.search(r"题目 id：([^\s]+)", user_prompt)
        question_id = match.group(1) if match else "0"
        return json.dumps(
            {
                "questions": [
                    {
                        "id": question_id,
                        "score": self.scores.pop(0),
                        "why": "验收",
                        "reference_answer": "",
                        "misconception_hit": False,
                        "certain": False,
                    }
                ],
                "session_misconception": None,
            },
            ensure_ascii=False,
        )


def make_rows() -> list[dict]:
    rows = []
    planned = [("90-100", 95)] * 3 + [("40-69", 60)] * 3 + [("0-39", 20)] * 2
    for index, (band, score) in enumerate(planned):
        rows.append(
            {
                "question_id": f"q{index}",
                "question_type": TYPES[index % len(TYPES)],
                "question_text": f"第 {index} 题",
                "reference_answer": "参考答案",
                "rubric_json": {"levels": [0, 40, 70, 90, 100]},
                "source_excerpt": "摘录",
                "answer": f"答案 {index}",
                "human_band": band,
                "skipped": False,
            }
        )
    for index in (8, 9):
        rows.append(
            {
                "question_id": f"q{index}",
                "question_type": TYPES[index % len(TYPES)],
                "question_text": f"第 {index} 题",
                "reference_answer": "参考答案",
                "rubric_json": {},
                "source_excerpt": "摘录",
                "answer": "",
                "human_band": "",
                "skipped": True,
            }
        )
    return rows


@pytest.mark.parametrize(
    ("score", "band"),
    [
        (0, "0-39"),
        (39, "0-39"),
        (40, "40-69"),
        (69, "40-69"),
        (70, "70-89"),
        (89, "70-89"),
        (90, "90-100"),
        (100, "90-100"),
    ],
)
def test_band_of(score: int, band: str) -> None:
    assert band_of(score) == band


def test_answer_template_covers_all_questions() -> None:
    questions = [
        {
            "question_id": f"q{index}",
            "question_type": TYPES[index % len(TYPES)],
            "question_text": "题干",
            "reference_answer": "参考答案",
            "rubric_json": {},
            "source_excerpt": "摘录",
        }
        for index in range(10)
    ]

    rows = answer_template(questions)

    assert len(rows) == 10
    assert all(row["answer"] == "" and row["human_band"] == "" for row in rows)
    assert all(row["skipped"] is False for row in rows)


def test_scoring_sheet_lists_type_and_reference() -> None:
    markdown = render_scoring_sheet(make_rows())

    assert "评分验收标准答案模板" in markdown
    assert "（concept）" in markdown
    assert "参考答案：参考答案" in markdown
    assert "人工档位：____" in markdown


def test_run_acceptance_passes_at_six_of_eight_and_skip_behavior() -> None:
    scorer = FakeScorer([95, 95, 95, 60, 60, 60, 20, 20])

    report = asyncio.run(run_acceptance(make_rows(), scorer))

    assert report["passed"] is True
    assert report["answered"] == 8
    assert report["skipped"] == 2
    assert report["consistent"] == 8
    assert report["needed"] == 6
    assert report["skipped_ok"] == 2
    assert scorer.calls == 8
    assert [item["calls"] for item in report["results"][8:]] == [0, 0]


def test_run_acceptance_fails_below_consistency_threshold() -> None:
    scorer = FakeScorer([95, 95, 95, 20, 20, 20, 75, 75])

    report = asyncio.run(run_acceptance(make_rows(), scorer))

    assert report["consistent"] == 3
    assert report["passed"] is False


def test_run_acceptance_requires_exactly_two_skips() -> None:
    rows = make_rows()
    rows[8]["skipped"] = False
    rows[8]["human_band"] = "70-89"
    scorer = FakeScorer([95, 95, 95, 60, 60, 60, 20, 20, 75])

    report = asyncio.run(run_acceptance(rows, scorer))

    assert report["answered"] == 9
    assert report["skipped"] == 1
    assert report["passed"] is False


def test_report_marks_skipped_rows() -> None:
    scorer = FakeScorer([95, 95, 95, 60, 60, 60, 20, 20])

    report = asyncio.run(run_acceptance(make_rows(), scorer))
    markdown = render_report(report)

    assert "结论：通过" in markdown
    assert "| q8 | 跳题 | - | - | 不评分 |" in markdown
