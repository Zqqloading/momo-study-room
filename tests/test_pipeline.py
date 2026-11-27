from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core.concepts import load_concepts
from core.confirm import main as confirm_main
from core.db import connect
from core.extraction import Extractor
from core.ingest import main as ingest_main
from core.ingestion import chunk_material, parse_material

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"


class FakeScorer:
    name = "fake"

    def __init__(self, response: str) -> None:
        self.response = response

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        return self.response


def answers(*values: str):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def test_pipeline_ingest_extract_confirm(tmp_path: Path) -> None:
    fixture = FIXTURES / "agent-basics.md"
    db = tmp_path / "app.db"

    assert ingest_main([str(fixture), "--db", str(db)]) == 0

    material = parse_material(fixture)
    parents = [chunk for chunk in chunk_material(material) if chunk.level == "parent"]
    response = json.dumps(
        {
            "concepts": [
                {
                    "name": "Agent",
                    "aliases": ["智能体"],
                    "plain_def": "能自己决定下一步做什么的程序",
                    "prerequisites": [],
                    "difficulty": 1,
                    "source_excerpt": "Agent 是能感知环境并自主采取行动的系统",
                },
                {
                    "name": "工具调用",
                    "aliases": ["function calling"],
                    "plain_def": "让模型调用外部工具拿到结果再继续想",
                    "prerequisites": ["Agent"],
                    "difficulty": 2,
                    "source_excerpt": "工具调用让模型调用外部工具拿到结果再继续想",
                },
            ]
        },
        ensure_ascii=False,
    )
    report = asyncio.run(
        Extractor(FakeScorer(response)).extract(
            parents,
            source_url="https://example.com/agent-basics",
            material_path=material.path,
        )
    )
    assert [candidate.name for candidate in report.candidates] == ["Agent", "工具调用"]

    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(
        json.dumps(
            {
                "material": {"path": material.path},
                "candidates": [candidate.to_dict() for candidate in report.candidates],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    yaml_path = tmp_path / "concepts.yaml"

    assert (
        confirm_main(
            [str(candidates_path), "--concepts", str(yaml_path), "--db", str(db)],
            input_fn=answers("c", "l", "c", "k"),
        )
        == 0
    )

    concepts = load_concepts(yaml_path)
    assert [concept.id for concept in concepts] == ["agent", "工具调用"]
    assert concepts[1].prerequisites == ("agent",)

    conn = connect(db)
    try:
        states = {
            row["id"]: dict(row) for row in conn.execute("SELECT * FROM concepts")
        }
        assert states["agent"]["status"] == "active"
        assert states["工具调用"]["status"] == "known"
        assert states["工具调用"]["mastery"] == 5

        joined = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM concept_sources cs
            JOIN material_chunks mc ON mc.id = cs.chunk_id
            """
        ).fetchone()["n"]
        assert joined == 2
        assert conn.execute("SELECT version FROM materials").fetchone()["version"] == 1
    finally:
        conn.close()

    # 同一材料再跑一次：哈希未变，不应产生新版本/新块。
    assert ingest_main([str(fixture), "--db", str(db)]) == 0
    conn = connect(db)
    try:
        assert conn.execute("SELECT version FROM materials").fetchone()["version"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM material_chunks").fetchone()["n"] == 5
    finally:
        conn.close()

    ingest_runs = _runs(db, "ingest")
    assert [run["status"] for run in ingest_runs] == ["succeeded", "succeeded"]
    assert json.loads(ingest_runs[0]["stats_json"])["materials"] == 1
    assert json.loads(ingest_runs[1]["stats_json"])["skipped_unchanged"] == 1
    confirm_runs = _runs(db, "confirm")
    assert len(confirm_runs) == 1
    assert confirm_runs[0]["status"] == "succeeded"


def _runs(db: Path, kind: str) -> list[dict[str, object]]:
    conn = connect(db)
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM pipeline_runs WHERE kind = ? ORDER BY id", (kind,)
            )
        ]
    finally:
        conn.close()


def test_reindex_cli_records_run(tmp_path: Path) -> None:
    from core.reindex import main as reindex_main

    db = tmp_path / "app.db"
    assert ingest_main([str(FIXTURES / "agent-basics.md"), "--db", str(db)]) == 0
    assert reindex_main(["--db", str(db), "--fts-only"]) == 0

    runs = _runs(db, "reindex")
    assert len(runs) == 1
    assert runs[0]["status"] == "succeeded"
    stats = json.loads(runs[0]["stats_json"])
    conn = connect(db)
    try:
        children = conn.execute(
            "SELECT COUNT(*) AS n FROM material_chunks WHERE level = 'child'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert stats["fts_rows"] == children


def test_reindex_prune_flag_removes_orphans(tmp_path: Path) -> None:
    from core.reindex import main as reindex_main

    db = tmp_path / "app.db"
    assert ingest_main([str(FIXTURES / "agent-basics.md"), "--db", str(db)]) == 0

    conn = connect(db)
    try:
        conn.execute(
            """
            INSERT INTO chunk_embeddings (chunk_id, model, dim, vector, created_at)
            VALUES ('ghost', 'fake', 4, X'00', '2026-11-23')
            """
        )
    finally:
        conn.close()

    assert reindex_main(["--db", str(db), "--fts-only", "--prune"]) == 0

    conn = connect(db)
    try:
        assert (
            conn.execute(
                "SELECT COUNT(*) AS n FROM chunk_embeddings WHERE chunk_id = 'ghost'"
            ).fetchone()["n"]
            == 0
        )
    finally:
        conn.close()


def test_extract_cli_records_failed_run_without_scorer(
    tmp_path: Path, monkeypatch
) -> None:
    import bff.config
    import bff.providers.registry
    from bff.providers.base import ProviderNotConfigured
    from core.extract import main as extract_main

    chunks = tmp_path / "chunks.json"
    assert (
        ingest_main(
            [str(FIXTURES / "agent-basics.md"), "--dry-run", "--out", str(chunks)]
        )
        == 0
    )

    monkeypatch.setattr(bff.config, "load_settings", lambda: object())

    def boom(*args, **kwargs):
        raise ProviderNotConfigured("scorer 未配置")

    monkeypatch.setattr(bff.providers.registry, "build_providers", boom)

    db = tmp_path / "app.db"
    assert extract_main([str(chunks), "--db", str(db)]) == 2
    runs = _runs(db, "extract")
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert "scorer" in (runs[0]["error"] or "")


class _Providers:
    def __init__(self, scorer) -> None:
        self.scorer = scorer
        self.modes = {"scorer": "deepseek"}

    async def aclose(self) -> None:
        return None


def test_emit_chunks_cli_pipeline_end_to_end(tmp_path: Path, monkeypatch) -> None:
    import bff.config
    import bff.providers.registry
    from core.extract import main as extract_main

    fixture = FIXTURES / "agent-basics.md"
    db = tmp_path / "app.db"
    chunks = tmp_path / "chunks.json"
    assert (
        ingest_main(
            [str(fixture), "--db", str(db), "--emit-chunks", "--out", str(chunks)]
        )
        == 0
    )

    response = json.dumps(
        {
            "concepts": [
                {
                    "name": "Agent",
                    "aliases": ["智能体"],
                    "plain_def": "能自己决定下一步做什么的程序",
                    "prerequisites": [],
                    "difficulty": 1,
                    "source_excerpt": "Agent 是能感知环境并自主采取行动的系统",
                }
            ]
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(bff.config, "load_settings", lambda: object())
    monkeypatch.setattr(
        bff.providers.registry,
        "build_providers",
        lambda *args, **kwargs: _Providers(FakeScorer(response)),
    )

    candidates = tmp_path / "candidates.json"
    yaml_path = tmp_path / "concepts.yaml"
    assert (
        extract_main(
            [
                str(chunks),
                "--db",
                str(db),
                "--concepts",
                str(yaml_path),
                "--out",
                str(candidates),
            ]
        )
        == 0
    )
    assert (
        confirm_main(
            [str(candidates), "--concepts", str(yaml_path), "--db", str(db)],
            input_fn=answers("c", "l"),
        )
        == 0
    )

    data = json.loads(candidates.read_text(encoding="utf-8"))
    assert data["candidates"]
    assert all("-v1-" in item["chunk_id"] for item in data["candidates"])

    conn = connect(db)
    try:
        versions = {
            row["material_version"]
            for row in conn.execute(
                """
                SELECT DISTINCT mc.material_version
                FROM concept_sources cs
                JOIN material_chunks mc ON mc.id = cs.chunk_id
                """
            )
        }
        assert versions == {1}
        assert conn.execute("SELECT COUNT(*) AS n FROM concept_sources").fetchone()["n"] == 1
    finally:
        conn.close()

    extract_runs = _runs(db, "extract")
    assert len(extract_runs) == 1
    assert extract_runs[0]["status"] == "succeeded"
    stats = json.loads(extract_runs[0]["stats_json"])
    assert stats["candidates"] == 1
