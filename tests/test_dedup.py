from __future__ import annotations

import asyncio
from dataclasses import replace

from support import make_coach


def bank_ids(store, started) -> list[str]:
    ids: list[str] = []
    for question in started.questions:
        row = store.question(question.id)
        assert row is not None
        ids.append(str(row["question_bank_id"]))
    return ids


def test_each_session_has_no_duplicate_questions() -> None:
    store, coach, _ = make_coach()
    try:
        started = asyncio.run(coach.start())
        ids = bank_ids(store, started)
        assert len(ids) == 5
        assert len(set(ids)) == 5
    finally:
        store.close()


def test_consecutive_sessions_use_different_questions() -> None:
    store, coach, _ = make_coach()
    try:
        first = bank_ids(store, asyncio.run(coach.start()))
        second = bank_ids(store, asyncio.run(coach.start()))
        assert first != second
        assert len(set(second)) == 5
    finally:
        store.close()


def test_unused_question_appears_in_next_session() -> None:
    store, coach, _ = make_coach()
    try:
        all_ids = {
            str(row["id"]) for row in store.bank_questions("agent-loop")
        }
        first = set(bank_ids(store, asyncio.run(coach.start())))
        second = set(bank_ids(store, asyncio.run(coach.start())))
        unused = all_ids - first
        assert unused
        # 题型配比会剩最多一个未用题留给下一场。
        assert len(unused & second) >= len(unused) - 1
    finally:
        store.close()


def test_due_concept_question_is_not_repeated_as_new() -> None:
    store, coach, _ = make_coach()
    try:
        state = store.concept_state("agent-loop")
        assert state is not None
        store.upsert_concept(replace(state, review_due_at="2026-11-23"))

        started = asyncio.run(coach.start())
        ids = bank_ids(store, started)
        assert len(ids) == len(set(ids))
    finally:
        store.close()
