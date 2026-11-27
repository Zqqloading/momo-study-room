from __future__ import annotations

import json
from pathlib import Path

from core.concepts import load_concepts
from core.confirm import main
from core.db import connect, init_schema
from core.store import Store

EXISTING = """version: 1
concepts:
  # keep me
  - id: existing
    name: Existing
    aliases: []
    plain_def: 已有概念
    difficulty: 1
    prerequisites: []
    source:
      material: materials/a.md
      url: https://example.com/a
      excerpt: 已有概念
"""


def candidate(
    concept_id: str,
    name: str,
    *,
    prerequisites: tuple[str, ...] = (),
    difficulty: int = 1,
    plain_def: str = "一句短定义",
) -> dict[str, object]:
    return {
        "id": concept_id,
        "name": name,
        "aliases": [],
        "plain_def": plain_def,
        "prerequisites": list(prerequisites),
        "prerequisite_names": [],
        "difficulty": difficulty,
        "source_url": "https://example.com/a",
        "source_excerpt": "Agent 是能自己决定下一步的程序",
        "chunk_id": "m-parent-001",
        "material_path": "materials/a.md",
        "flags": [],
    }


def write_candidates(path: Path, items: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {"material": {"path": "materials/a.md"}, "candidates": items},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def answers(*values: str):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def seed_chunk(db: Path, chunk_id: str = "m-parent-001") -> None:
    conn = connect(db)
    try:
        init_schema(conn)
        store = Store(conn)
        store.upsert_material(
            material_id="m",
            title="m",
            path="materials/a.md",
            format="md",
            content_hash="x" * 64,
            version=1,
            added_at="2026-11-23T00:00:00",
            status="active",
            source_url="https://example.com/a",
            tags_json=None,
        )
        store.insert_chunks(
            [
                {
                    "id": chunk_id,
                    "material_id": "m",
                    "material_version": 1,
                    "parent_id": None,
                    "level": "parent",
                    "heading_path": "",
                    "text": "Agent 是能自己决定下一步的程序",
                    "content_hash": "y" * 64,
                    "token_count": 10,
                    "ordinal": 1,
                    "source_url": "https://example.com/a",
                }
            ]
        )
    finally:
        conn.close()


def test_confirm_writes_yaml_and_statuses(tmp_path: Path) -> None:
    yaml_path = tmp_path / "concepts.yaml"
    yaml_path.write_text(EXISTING, encoding="utf-8")
    candidates_path = tmp_path / "candidates.json"
    write_candidates(
        candidates_path,
        [
            candidate("agent", "Agent"),
            candidate("tool-calling", "工具调用", prerequisites=("agent",), difficulty=2),
        ],
    )
    db = tmp_path / "app.db"
    seed_chunk(db)

    assert (
        main(
            [str(candidates_path), "--concepts", str(yaml_path), "--db", str(db)],
            input_fn=answers("c", "l", "c", "k"),
        )
        == 0
    )

    text = yaml_path.read_text(encoding="utf-8")
    assert "# keep me" in text
    concepts = load_concepts(yaml_path)
    assert [concept.id for concept in concepts] == ["existing", "agent", "tool-calling"]
    assert concepts[2].prerequisites == ("agent",)

    conn = connect(db)
    try:
        states = {
            row["id"]: dict(row) for row in conn.execute("SELECT * FROM concepts")
        }
        assert states["agent"]["status"] == "active"
        assert states["agent"]["mastery"] == 0
        assert states["tool-calling"]["status"] == "known"
        assert states["tool-calling"]["mastery"] == 5

        sources = conn.execute(
            "SELECT concept_id, chunk_id FROM concept_sources ORDER BY concept_id"
        ).fetchall()
        assert [row["concept_id"] for row in sources] == ["agent", "tool-calling"]
    finally:
        conn.close()

    data = json.loads(candidates_path.read_text(encoding="utf-8"))
    assert data["candidates"][0]["review"]["quality"] == "correct"
    assert data["candidates"][0]["review"]["decision"] == "learn"


def test_confirm_wrong_quality_skips_yaml_and_db(tmp_path: Path) -> None:
    yaml_path = tmp_path / "concepts.yaml"
    candidates_path = tmp_path / "candidates.json"
    write_candidates(candidates_path, [candidate("agent", "Agent")])
    db = tmp_path / "app.db"

    assert (
        main(
            [str(candidates_path), "--concepts", str(yaml_path), "--db", str(db)],
            input_fn=answers("w", "摘录不对"),
        )
        == 0
    )

    assert not yaml_path.exists()
    assert not db.exists()
    data = json.loads(candidates_path.read_text(encoding="utf-8"))
    assert data["candidates"][0]["review"]["quality"] == "wrong"
    assert data["candidates"][0]["review"]["reason"] == "摘录不对"


def test_confirm_drops_unconfirmed_prerequisite(tmp_path: Path, capsys) -> None:
    yaml_path = tmp_path / "concepts.yaml"
    candidates_path = tmp_path / "candidates.json"
    write_candidates(
        candidates_path,
        [
            candidate("agent", "Agent"),
            candidate("tool-calling", "工具调用", prerequisites=("agent",)),
        ],
    )
    db = tmp_path / "app.db"
    seed_chunk(db)

    assert (
        main(
            [str(candidates_path), "--concepts", str(yaml_path), "--db", str(db)],
            input_fn=answers("w", "抽错了", "c", "l"),
        )
        == 0
    )

    concepts = load_concepts(yaml_path)
    assert [concept.id for concept in concepts] == ["tool-calling"]
    assert concepts[0].prerequisites == ()
    assert "丢弃未确认的前置" in capsys.readouterr().err


def test_reapply_writes_statuses_to_new_db(tmp_path: Path) -> None:
    yaml_path = tmp_path / "concepts.yaml"
    candidates_path = tmp_path / "candidates.json"
    write_candidates(candidates_path, [candidate("agent", "Agent")])
    first_db = tmp_path / "first.db"
    second_db = tmp_path / "second.db"
    seed_chunk(first_db)
    seed_chunk(second_db)

    assert (
        main(
            [str(candidates_path), "--concepts", str(yaml_path), "--db", str(first_db)],
            input_fn=answers("c", "l"),
        )
        == 0
    )
    assert (
        main(
            [
                str(candidates_path),
                "--concepts",
                str(yaml_path),
                "--db",
                str(second_db),
                "--reapply",
            ]
        )
        == 0
    )

    conn = connect(second_db)
    try:
        row = conn.execute("SELECT status FROM concepts WHERE id = 'agent'").fetchone()
        assert row is not None
        assert row["status"] == "active"
    finally:
        conn.close()


def test_yaml_validation_failure_leaves_old_file(tmp_path: Path) -> None:
    yaml_path = tmp_path / "concepts.yaml"
    yaml_path.write_text(EXISTING, encoding="utf-8")
    before = yaml_path.read_bytes()
    candidates_path = tmp_path / "candidates.json"
    write_candidates(
        candidates_path,
        [
            candidate("a", "A", prerequisites=("b",)),
            candidate("b", "B", prerequisites=("a",)),
        ],
    )

    db = tmp_path / "app.db"
    seed_chunk(db)
    assert (
        main(
            [
                str(candidates_path),
                "--concepts",
                str(yaml_path),
                "--db",
                str(db),
            ],
            input_fn=answers("c", "l", "c", "l"),
        )
        == 1
    )
    assert yaml_path.read_bytes() == before
    conn = connect(db)
    try:
        runs = conn.execute(
            "SELECT status FROM pipeline_runs WHERE kind = 'confirm'"
        ).fetchall()
        assert len(runs) == 1
        assert runs[0]["status"] == "failed"
    finally:
        conn.close()


def test_confirm_rejects_dangling_source(tmp_path: Path, capsys) -> None:
    yaml_path = tmp_path / "concepts.yaml"
    candidates_path = tmp_path / "candidates.json"
    write_candidates(candidates_path, [candidate("agent", "Agent")])
    db = tmp_path / "app.db"

    assert (
        main(
            [str(candidates_path), "--concepts", str(yaml_path), "--db", str(db)],
            input_fn=answers("c", "l"),
        )
        == 1
    )

    assert not yaml_path.exists()
    assert "出处校验失败" in capsys.readouterr().err
    conn = connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM concepts").fetchone()["n"] == 0
        assert (
            conn.execute("SELECT COUNT(*) AS n FROM concept_sources").fetchone()["n"] == 0
        )
        runs = conn.execute(
            "SELECT status, error FROM pipeline_runs WHERE kind = 'confirm'"
        ).fetchall()
        assert len(runs) == 1
        assert runs[0]["status"] == "failed"
        assert "出处校验失败" in (runs[0]["error"] or "")
    finally:
        conn.close()


def test_confirm_rejects_missing_chunk_id(tmp_path: Path, capsys) -> None:
    yaml_path = tmp_path / "concepts.yaml"
    candidates_path = tmp_path / "candidates.json"
    item = candidate("agent", "Agent")
    item["chunk_id"] = None
    write_candidates(candidates_path, [item])
    db = tmp_path / "app.db"

    assert (
        main(
            [str(candidates_path), "--concepts", str(yaml_path), "--db", str(db)],
            input_fn=answers("c", "l"),
        )
        == 1
    )

    assert not yaml_path.exists()
    assert "缺少 chunk_id" in capsys.readouterr().err


def test_reapply_rejects_dangling_source(tmp_path: Path) -> None:
    yaml_path = tmp_path / "concepts.yaml"
    candidates_path = tmp_path / "candidates.json"
    items = [candidate("agent", "Agent")]
    items[0]["review"] = {"quality": "correct", "decision": "learn", "reason": None}
    write_candidates(candidates_path, items)
    db = tmp_path / "app.db"

    assert (
        main(
            [
                str(candidates_path),
                "--concepts",
                str(yaml_path),
                "--db",
                str(db),
                "--reapply",
            ]
        )
        == 1
    )

    conn = connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM concepts").fetchone()["n"] == 0
    finally:
        conn.close()
