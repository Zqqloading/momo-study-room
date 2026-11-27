from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from core.concepts import ConceptsError, load_concepts, sync_runtime
from core.db import connect, init_schema
from core.models import ConceptState
from core.store import Store

BASE = {
    "version": 1,
    "concepts": [
        {
            "id": "agent",
            "name": "Agent",
            "aliases": ["智能体"],
            "plain_def": "能自己决定下一步做什么的程序",
            "difficulty": 1,
            "prerequisites": [],
            "source": {
                "material": "materials/agent-basics.md",
                "url": "https://example.com/agent",
                "excerpt": "Agent 是能感知环境并自主行动的系统。",
            },
        },
        {
            "id": "tool-calling",
            "name": "工具调用",
            "aliases": ["function calling"],
            "plain_def": "让模型调用外部工具拿到结果再继续想",
            "difficulty": 2,
            "prerequisites": ["agent"],
            "source": {
                "url": "https://example.com/tools",
                "excerpt": "模型通过工具描述决定何时调用哪个函数。",
            },
        },
    ],
}


def write_yaml(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "concepts.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def make_store() -> Store:
    conn = connect(":memory:")
    init_schema(conn)
    return Store(conn)


def test_loads_valid_concepts(tmp_path) -> None:
    concepts = load_concepts(write_yaml(tmp_path, BASE))
    assert [concept.id for concept in concepts] == ["agent", "tool-calling"]
    assert concepts[0].aliases == ("智能体",)
    assert concepts[1].prerequisites == ("agent",)
    assert concepts[0].source.material == "materials/agent-basics.md"
    assert concepts[1].source.material is None


def test_rejects_duplicate_ids(tmp_path) -> None:
    data = copy.deepcopy(BASE)
    data["concepts"].append(copy.deepcopy(data["concepts"][0]))
    with pytest.raises(ConceptsError, match="id 重复"):
        load_concepts(write_yaml(tmp_path, data))


def test_rejects_missing_prerequisite(tmp_path) -> None:
    data = copy.deepcopy(BASE)
    data["concepts"][1]["prerequisites"] = ["missing"]
    with pytest.raises(ConceptsError, match="前置不存在"):
        load_concepts(write_yaml(tmp_path, data))


def test_rejects_cycle(tmp_path) -> None:
    data = copy.deepcopy(BASE)
    data["concepts"][0]["prerequisites"] = ["tool-calling"]
    with pytest.raises(ConceptsError, match="成环"):
        load_concepts(write_yaml(tmp_path, data))


@pytest.mark.parametrize(
    ("path", "match"),
    [
        (("plain_def",), "plain_def"),
        (("source", "url"), "source.url"),
        (("source", "excerpt"), "source.excerpt"),
        (("difficulty",), "difficulty"),
    ],
)
def test_rejects_bad_fields(tmp_path, path: tuple[str, ...], match: str) -> None:
    data = copy.deepcopy(BASE)
    target = data["concepts"][0]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = "" if match != "difficulty" else 9
    with pytest.raises(ConceptsError, match=match):
        load_concepts(write_yaml(tmp_path, data))


def test_rejects_wrong_version(tmp_path) -> None:
    data = copy.deepcopy(BASE)
    data["version"] = 2
    with pytest.raises(ConceptsError, match="version"):
        load_concepts(write_yaml(tmp_path, data))


def test_sync_adds_proposed_and_preserves_mastery(tmp_path) -> None:
    store = make_store()
    try:
        store.upsert_concept(
            ConceptState(id="agent", mastery=3, status="active", last_seen="2026-11-01")
        )
        report = sync_runtime(store, load_concepts(write_yaml(tmp_path, BASE)))
        assert report.added == ("tool-calling",)
        assert report.orphaned == ()
        assert report.restored == ()

        agent = store.concept_state("agent")
        assert agent is not None
        assert agent.mastery == 3
        assert agent.status == "active"

        tools = store.concept_state("tool-calling")
        assert tools is not None
        assert tools.status == "proposed"
        assert tools.mastery == 0
    finally:
        store.close()


def test_sync_rolls_back_on_failure(tmp_path, monkeypatch) -> None:
    store = make_store()
    try:
        original = store.upsert_concept
        calls = {"count": 0}

        def flaky(state):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("boom")
            original(state)

        monkeypatch.setattr(store, "upsert_concept", flaky)
        with pytest.raises(RuntimeError):
            sync_runtime(store, load_concepts(write_yaml(tmp_path, BASE)))

        assert store.concept_states() == []
    finally:
        store.close()


def test_sync_orphans_removed_and_restores_prior_status(tmp_path) -> None:
    store = make_store()
    try:
        store.upsert_concept(ConceptState(id="agent", mastery=3, status="active"))
        data = copy.deepcopy(BASE)
        data["concepts"] = [data["concepts"][1]]  # 去掉 agent
        data["concepts"][0]["prerequisites"] = []  # 否则前置校验会先报错
        report = sync_runtime(store, load_concepts(write_yaml(tmp_path, data)))
        assert report.orphaned == ("agent",)

        agent = store.concept_state("agent")
        assert agent is not None
        assert agent.status == "orphaned"
        assert agent.prior_status == "active"
        assert agent.mastery == 3

        report = sync_runtime(store, load_concepts(write_yaml(tmp_path, BASE)))
        assert report.restored == ("agent",)
        agent = store.concept_state("agent")
        assert agent is not None
        assert agent.status == "active"
        assert agent.prior_status is None
        assert agent.mastery == 3
    finally:
        store.close()
