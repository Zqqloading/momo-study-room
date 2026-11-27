from __future__ import annotations

import pytest

from core.eval_questions import (
    blind_rows,
    evaluate_question_labels,
    labels_template,
    render_blind_markdown,
    render_report,
)

TYPES = (
    "concept",
    "business",
    "tradeoff",
    "cost_risk",
    "synthesis",
)


def make_questions() -> list[dict]:
    return [
        {
            "question_id": f"q{index}",
            "concept_id": "mvp",
            "question_type": TYPES[index % len(TYPES)],
            "question_text": f"第 {index} 题题干",
            "source_excerpt": f"第 {index} 题摘录",
            "reference_answer": "参考答案",
            "rubric_json": {"levels": []},
        }
        for index in range(10)
    ]


def make_labels(questions: list[dict]) -> list[dict]:
    return [
        {
            "question_id": item["question_id"],
            "question_type": item["question_type"],
            "understanding": "理解",
            "perspective": "业务",
            "source": "可",
        }
        for item in questions
    ]


def test_blind_rows_hide_claimed_type_and_rubric() -> None:
    rows = blind_rows(make_questions())

    assert set(rows[0]) == {"question_id", "question_text", "source_excerpt"}


def test_labels_template_is_blank() -> None:
    rows = labels_template(make_questions())

    assert len(rows) == 10
    assert all(
        row["question_type"] == ""
        and row["understanding"] == ""
        and row["perspective"] == ""
        and row["source"] == ""
        for row in rows
    )


def test_blind_markdown_lists_definitions_and_questions() -> None:
    markdown = render_blind_markdown(make_questions())

    assert "题型定义" in markdown
    assert "tradeoff" in markdown
    assert "第 3 题题干" in markdown
    assert "第 3 题摘录" in markdown
    assert "题型：____" in markdown


def test_evaluate_passes_when_all_labels_match() -> None:
    questions = make_questions()
    report = evaluate_question_labels(questions, make_labels(questions))

    assert report["passed"] is True
    assert report["counts"] == {
        "type": 10,
        "understanding": 10,
        "perspective": 10,
        "source": 10,
    }
    assert report["failures"] == []


def test_evaluate_fails_on_programmer_perspective() -> None:
    questions = make_questions()
    labels = make_labels(questions)
    labels[4]["perspective"] = "程序"

    report = evaluate_question_labels(questions, labels)

    assert report["passed"] is False
    assert report["counts"]["perspective"] == 9
    assert any(
        item["question_id"] == "q4" for item in report["failures"]
    )


def test_evaluate_fails_on_wrong_type_and_rote() -> None:
    questions = make_questions()
    labels = make_labels(questions)
    labels[0]["question_type"] = "business"
    labels[1]["question_type"] = "business"
    labels[2]["question_type"] = "business"
    labels[3]["question_type"] = "concept"
    labels[3]["understanding"] = "背诵"
    labels[4]["understanding"] = "背诵"

    report = evaluate_question_labels(questions, labels)

    assert report["passed"] is False
    assert report["counts"]["type"] == 7
    assert report["counts"]["understanding"] == 8


def test_evaluate_requires_all_labels() -> None:
    questions = make_questions()
    labels = make_labels(questions)[:-1]

    with pytest.raises(ValueError, match="缺少标签"):
        evaluate_question_labels(questions, labels)


def test_report_renders_failure_details() -> None:
    questions = make_questions()
    labels = make_labels(questions)
    labels[2]["source"] = "不可"

    report = evaluate_question_labels(questions, labels)
    markdown = render_report(report)

    assert "结论：不通过" in markdown
    assert "题目 q2" in markdown
    assert "溯源=False" in markdown
