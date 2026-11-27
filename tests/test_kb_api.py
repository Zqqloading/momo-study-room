from __future__ import annotations

from contextlib import closing
from dataclasses import replace

from fastapi.testclient import TestClient

from bff.config import load_settings
from bff.main import create_app
from core.db import connect
from core.store import Store


def make_env(tmp_path) -> dict[str, str]:
    return {
        "PROVIDER_MODE": "fake",
        "DB_PATH": str(tmp_path / "app.db"),
        "DATA_DIR": str(tmp_path / "data"),
        "CONTENT_DIR": str(tmp_path),
    }


def _store(tmp_path) -> Store:
    return Store(connect(tmp_path / "app.db"))


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        return "{}"

    async def complete(self, *args, **kwargs) -> str:
        self.calls += 1
        return ""

    async def synthesize(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("不应调用 TTS")

    async def search(self, *args, **kwargs):
        self.calls += 1
        return []


def _counts(store: Store) -> tuple[int, int, int]:
    conn = store.conn
    sessions = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
    agents = conn.execute("SELECT COUNT(*) AS n FROM agent_sessions").fetchone()["n"]
    concepts = conn.execute("SELECT COUNT(*) AS n FROM concepts").fetchone()["n"]
    return (int(sessions), int(agents), int(concepts))


def test_proposal_endpoint_returns_read_only_preview(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client, closing(_store(tmp_path)) as store:
        before_counts = _counts(store)
        before_states = store.concept_states()
        scorer = CountingProvider()
        llm = CountingProvider()
        tts = CountingProvider()
        search = CountingProvider()
        app.state.coach._scorer = scorer
        app.state.providers.llm = llm
        app.state.providers.tts = tts
        app.state.providers.search = search

        response = client.get("/api/kb/unit/proposal")
        assert response.status_code == 200
        payload = response.json()
        assert payload["available"] is True
        assert payload["kind"] == "daily"
        assert payload["main"]["id"] == "agent-loop"
        assert payload["main"]["mastery_label"] == "未掌握"
        assert payload["review"] is None
        assert payload["question_count"] == 5
        assert len(payload["slots"]) == 5
        assert payload["slots"][0]["type"] == "concept"
        assert payload["slots"][0]["role"] == "new"
        assert payload["main"]["reason_kind"] == "no_signal"
        assert "从未学过" in payload["main"]["reason"]

        assert _counts(store) == before_counts
        assert store.concept_states() == before_states
        assert scorer.calls == 0
        assert llm.calls == 0
        assert tts.calls == 0
        assert search.calls == 0


def test_overview_endpoint_returns_stats_and_concepts(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client, closing(_store(tmp_path)) as store:
        before_counts = _counts(store)
        response = client.get("/api/kb/overview")
        assert response.status_code == 200
        payload = response.json()
        assert payload["stats"]["active"] == 3
        assert payload["stats"]["avg_mastery"] == 0.0
        assert payload["stats"]["due"] == 0
        assert payload["stats"]["weak"] == 0
        assert len(payload["stats"]["distribution"]) == 6
        assert payload["stats"]["distribution"][0]["count"] == 3
        assert {item["id"] for item in payload["concepts"]} == {
            "agent-loop",
            "tool-use",
            "memory",
        }
        assert payload["recent_units"] == []
        assert _counts(store) == before_counts


def test_proposal_unavailable_returns_200(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client, closing(_store(tmp_path)) as store:
        for state in store.concept_states():
            store.upsert_concept(replace(state, status="known"))
        store.conn.commit()
        response = client.get("/api/kb/unit/proposal")
        assert response.status_code == 200
        payload = response.json()
        assert payload["available"] is False
        assert payload["main"] is None
        assert payload["review"] is None
        assert "没有在学概念" in payload["reason"]


def test_overview_empty_after_concepts_removed(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client, closing(_store(tmp_path)) as store:
        store.conn.execute("DELETE FROM concepts")
        store.conn.commit()
        response = client.get("/api/kb/overview")
        assert response.status_code == 200
        payload = response.json()
        assert payload["stats"]["active"] == 0
        assert payload["stats"]["avg_mastery"] is None
        assert payload["concepts"] == []
        assert all(item["count"] == 0 for item in payload["stats"]["distribution"])


def test_api_routes_are_not_swallowed_by_static(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/kb/overview").headers["content-type"].startswith(
            "application/json"
        )
        assert client.get("/api/kb/unit/proposal").headers["content-type"].startswith(
            "application/json"
        )


def test_overview_weak_uses_recent_miss(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client, closing(_store(tmp_path)) as store:
        today = app.state.clock.today()
        state = store.concept_state("agent-loop")
        assert state is not None
        store.upsert_concept(replace(state, mastery=4, last_seen=today))
        store.conn.commit()

        store.start_agent_session(
            session_id="low",
            kind="daily",
            date=today,
            started_at=f"{today}T20:00:00",
        )
        question_id = store.add_question(
            session_id="low",
            question_bank_id=None,
            concept_id="agent-loop",
            role="new",
            kind="apply",
            text="题",
            rubric_json={},
            source_url="fixture://low",
            source_excerpt="出处",
            created_at=f"{today}T20:01:00",
        )
        store.save_answer(question_id, text="答", score=40, feedback="低分")

        response = client.get("/api/kb/overview")
        assert response.status_code == 200
        payload = response.json()
        assert payload["stats"]["weak"] == 1
