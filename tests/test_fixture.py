from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from core.db import connect, init_schema
from core.fixture import load_fixture
from core.store import Store

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "seeds" / "fixture"
CONCEPTS = FIXTURE_DIR / "fixture-concepts.yaml"
BANK = FIXTURE_DIR / "fixture-question-bank.json"


def make_store() -> Store:
    conn = connect(":memory:")
    init_schema(conn)
    return Store(conn)


def test_load_fixture_imports_active_concepts_and_bank() -> None:
    store = make_store()
    try:
        load_fixture(store, CONCEPTS, BANK)
        states = store.concept_states()
        assert {state.id for state in states} == {"agent-loop", "tool-use", "memory"}
        assert all(state.status == "active" for state in states)
        for concept_id in ("agent-loop", "tool-use", "memory"):
            assert len(store.bank_questions(concept_id)) >= 6
    finally:
        store.close()


def test_load_fixture_is_idempotent_and_keeps_mastery() -> None:
    store = make_store()
    try:
        load_fixture(store, CONCEPTS, BANK)
        before = len(store.bank_questions("agent-loop"))
        state = store.concept_state("agent-loop")
        assert state is not None
        store.upsert_concept(replace(state, mastery=3))
        load_fixture(store, CONCEPTS, BANK)
        assert len(store.bank_questions("agent-loop")) == before
        reloaded = store.concept_state("agent-loop")
        assert reloaded is not None
        assert reloaded.mastery == 3
        assert reloaded.status == "active"
    finally:
        store.close()
