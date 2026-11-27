from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.ingest import main
from core.ingestion import (
    CHILD_MAX,
    IngestError,
    chunk_material,
    count_tokens,
    parse_material,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"


def test_parse_markdown_front_matter_and_code_fence() -> None:
    material = parse_material(FIXTURES / "agent-basics.md")

    assert material.format == "md"
    assert material.title == "agent-basics"
    assert material.source_url == "https://example.com/agent-basics"

    headings = [block.text for block in material.blocks if block.kind == "heading"]
    assert headings == ["Agent 基础", "工具调用", "上下文窗口"]

    code = [block.text for block in material.blocks if block.kind == "code"]
    assert len(code) == 1
    assert "# 这不是标题" in code[0]


def test_parse_html_prefers_article_and_strips_nav() -> None:
    material = parse_material(FIXTURES / "article.html")

    assert material.format == "html"
    assert material.title == "Agent 基础"
    assert material.source_url == "https://example.com/agent"

    text = "\n".join(block.text for block in material.blocks)
    assert "Agent 是能感知" in text
    assert "工具调用让模型" in text
    assert "裸文本也要" in text
    assert "导航不要" not in text
    assert "页脚不要" not in text
    assert "脚本不要" not in text


def test_count_tokens_character_approximation() -> None:
    assert count_tokens("") == 0
    assert count_tokens("中" * 10) == 10
    assert count_tokens("abcd" * 10) == 10
    assert count_tokens("中文abcd") == 3


def test_unsupported_format_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(IngestError):
        parse_material(path)


def test_parent_and_child_chunk_sizes(tmp_path: Path) -> None:
    path = tmp_path / "no-headings.md"
    path.write_text("\n\n".join(["中" * 700, "中" * 700]), encoding="utf-8")
    chunks = chunk_material(parse_material(path))

    parents = [chunk for chunk in chunks if chunk.level == "parent"]
    children = [chunk for chunk in chunks if chunk.level == "child"]
    assert len(parents) == 2
    for parent in parents:
        assert 600 <= parent.token_count <= 1000
        assert "no_heading" in parent.flags

    for child in children:
        if "short" not in child.flags and "oversized" not in child.flags:
            assert 80 <= child.token_count <= 250

    first_parent_children = [
        child for child in children if child.parent_id == parents[0].id
    ]
    assert len(first_parent_children) >= 2
    previous = first_parent_children[0]
    overlap = previous.text[-max(1, int(len(previous.text) * 0.1)) :]
    assert first_parent_children[1].text.startswith(overlap)


def test_small_code_block_stays_separate_from_paragraphs() -> None:
    chunks = chunk_material(parse_material(FIXTURES / "agent-basics.md"))
    children = [chunk for chunk in chunks if chunk.level == "child"]

    code_children = [child for child in children if "def call_tool" in child.text]
    assert len(code_children) == 1
    assert "Agent 是" not in code_children[0].text
    assert "上下文窗口" not in code_children[0].text


def test_oversized_code_block_is_flagged_not_split(tmp_path: Path) -> None:
    path = tmp_path / "big-code.md"
    path.write_text("# 大代码\n\n```\n" + "x" * 5000 + "\n```\n", encoding="utf-8")
    chunks = chunk_material(parse_material(path))

    parent = next(chunk for chunk in chunks if chunk.level == "parent")
    child = next(chunk for chunk in chunks if chunk.level == "child")
    assert "oversized" in parent.flags
    assert "oversized" in child.flags
    assert child.text == "x" * 5000


def test_oversized_table_splits_by_row_groups(tmp_path: Path) -> None:
    rows = "\n".join(
        f"| 概念{i} | 这是第 {i} 行的说明文字，用来把表格撑到超过子块上限 |"
        for i in range(1, 41)
    )
    body = f"# 表\n\n| 名称 | 说明 |\n| --- | --- |\n{rows}\n"
    path = tmp_path / "table.md"
    path.write_text(body, encoding="utf-8")

    chunks = chunk_material(parse_material(path))
    tables = [
        chunk
        for chunk in chunks
        if chunk.level == "child" and chunk.text.startswith("|")
    ]
    assert len(tables) > 1
    for chunk in tables:
        lines = chunk.text.splitlines()
        assert lines[:2] == ["| 名称 | 说明 |", "| --- | --- |"]
        assert "table_split" in chunk.flags
        assert count_tokens(chunk.text) <= CHILD_MAX or "oversized" in chunk.flags


def test_cli_dry_run_writes_chunks_json_without_db(tmp_path: Path) -> None:
    out = tmp_path / "chunks.json"
    db = tmp_path / "dry.db"
    assert (
        main(
            [
                str(FIXTURES / "agent-basics.md"),
                "--dry-run",
                "--out",
                str(out),
                "--db",
                str(db),
            ]
        )
        == 0
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["material"]["title"] == "agent-basics"
    assert payload["material"]["source_url"] == "https://example.com/agent-basics"
    assert payload["material"]["tags"] == ["agent", "basics"]
    assert payload["chunks"]
    assert {chunk["level"] for chunk in payload["chunks"]} == {"parent", "child"}
    assert not db.exists()


def test_cli_writes_material_and_chunks(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    assert main([str(FIXTURES / "agent-basics.md"), "--db", str(db)]) == 0

    from core.db import connect

    conn = connect(db)
    try:
        material = conn.execute("SELECT * FROM materials").fetchone()
        assert material is not None
        assert material["version"] == 1
        assert len(material["content_hash"]) == 64
        assert material["source_url"] == "https://example.com/agent-basics"

        counts = {
            row["level"]: row["count"]
            for row in conn.execute(
                "SELECT level, COUNT(*) AS count FROM material_chunks GROUP BY level"
            )
        }
        assert counts.get("parent", 0) >= 1
        assert counts.get("child", 0) >= 1

        urls = {
            row["source_url"]
            for row in conn.execute("SELECT source_url FROM material_chunks")
        }
        assert urls == {"https://example.com/agent-basics"}
    finally:
        conn.close()


def test_cli_bumps_version_and_keeps_old_chunks(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("# Agent\n\nAgent 是能自己决定下一步的程序。\n", encoding="utf-8")
    db = tmp_path / "app.db"

    assert main([str(path), "--db", str(db)]) == 0
    assert main([str(path), "--db", str(db)]) == 0  # 未变，不重复写

    path.write_text(
        "# Agent\n\nAgent 是能自己决定下一步的程序。\n\n工具调用让模型调用外部工具。\n",
        encoding="utf-8",
    )
    assert main([str(path), "--db", str(db)]) == 0

    from core.db import connect

    conn = connect(db)
    try:
        material = conn.execute("SELECT * FROM materials WHERE id = 'note'").fetchone()
        assert material is not None
        assert material["version"] == 2

        versions = {
            row["material_version"]
            for row in conn.execute("SELECT material_version FROM material_chunks")
        }
        assert versions == {1, 2}
    finally:
        conn.close()


def test_cli_rename_same_content_keeps_material_id(tmp_path: Path) -> None:
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    body = "# Agent\n\nAgent 是能自己决定下一步的程序。\n"
    old.write_text(body, encoding="utf-8")
    db = tmp_path / "app.db"

    assert main([str(old), "--db", str(db)]) == 0
    old.unlink()
    new.write_text(body, encoding="utf-8")
    assert main([str(new), "--db", str(db)]) == 0

    from core.db import connect

    conn = connect(db)
    try:
        rows = conn.execute("SELECT id, path, version FROM materials").fetchall()
        assert len(rows) == 1
        assert rows[0]["id"] == "old"
        assert rows[0]["path"] == str(new)
        assert rows[0]["version"] == 1
    finally:
        conn.close()


def test_emit_chunks_on_new_material_uses_v1(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    out = tmp_path / "chunks.json"
    assert (
        main(
            [
                str(FIXTURES / "agent-basics.md"),
                "--db",
                str(db),
                "--emit-chunks",
                "--out",
                str(out),
            ]
        )
        == 0
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["chunks"]
    assert {chunk["material_version"] for chunk in payload["chunks"]} == {1}
    assert all("-v1-" in chunk["id"] for chunk in payload["chunks"])


def test_emit_chunks_after_update_uses_new_version(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("# Agent\n\nAgent 是能自己决定下一步的程序。\n", encoding="utf-8")
    db = tmp_path / "app.db"
    out = tmp_path / "chunks.json"

    assert main([str(path), "--db", str(db)]) == 0
    path.write_text(
        "# Agent\n\nAgent 是能自己决定下一步的程序。\n\n工具调用让模型调用外部工具。\n",
        encoding="utf-8",
    )
    assert (
        main([str(path), "--db", str(db), "--emit-chunks", "--out", str(out)]) == 0
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert {chunk["material_version"] for chunk in payload["chunks"]} == {2}
    assert all("-v2-" in chunk["id"] for chunk in payload["chunks"])


def test_emit_chunks_on_unchanged_material_keeps_version(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("# Agent\n\nAgent 是能自己决定下一步的程序。\n", encoding="utf-8")
    db = tmp_path / "app.db"
    out = tmp_path / "chunks.json"

    assert main([str(path), "--db", str(db)]) == 0

    from core.db import connect

    conn = connect(db)
    try:
        before = conn.execute("SELECT COUNT(*) AS n FROM material_chunks").fetchone()["n"]
    finally:
        conn.close()

    assert (
        main([str(path), "--db", str(db), "--emit-chunks", "--out", str(out)]) == 0
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert {chunk["material_version"] for chunk in payload["chunks"]} == {1}

    conn = connect(db)
    try:
        after = conn.execute("SELECT COUNT(*) AS n FROM material_chunks").fetchone()["n"]
    finally:
        conn.close()
    assert after == before


def test_emit_chunks_after_rename_keeps_material_id(tmp_path: Path) -> None:
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    body = "# Agent\n\nAgent 是能自己决定下一步的程序。\n"
    old.write_text(body, encoding="utf-8")
    db = tmp_path / "app.db"
    out = tmp_path / "chunks.json"

    assert main([str(old), "--db", str(db)]) == 0
    old.unlink()
    new.write_text(body, encoding="utf-8")
    assert (
        main([str(new), "--db", str(db), "--emit-chunks", "--out", str(out)]) == 0
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["chunks"]
    assert all(chunk["id"].startswith("old-v1-") for chunk in payload["chunks"])
    assert all(chunk["material_id"] == "old" for chunk in payload["chunks"])


def test_update_after_rename_bumps_same_material(tmp_path: Path) -> None:
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    old.write_text("# Agent\n\nAgent 是能自己决定下一步的程序。\n", encoding="utf-8")
    db = tmp_path / "app.db"

    assert main([str(old), "--db", str(db)]) == 0
    old.unlink()
    new.write_text("# Agent\n\nAgent 是能自己决定下一步的程序。\n", encoding="utf-8")
    assert main([str(new), "--db", str(db)]) == 0

    new.write_text(
        "# Agent\n\nAgent 是能自己决定下一步的程序。\n\n工具调用让模型调用外部工具。\n",
        encoding="utf-8",
    )
    assert main([str(new), "--db", str(db)]) == 0

    from core.db import connect

    conn = connect(db)
    try:
        rows = conn.execute("SELECT id, path, version FROM materials").fetchall()
        assert len(rows) == 1
        assert rows[0]["id"] == "old"
        assert rows[0]["path"] == str(new)
        assert rows[0]["version"] == 2
        ids = {row["id"] for row in conn.execute("SELECT id FROM material_chunks")}
        assert any(chunk_id.startswith("old-v2-") for chunk_id in ids)
    finally:
        conn.close()


def test_emit_chunks_after_rename_unchanged_keeps_material_id(tmp_path: Path) -> None:
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    body = "# Agent\n\nAgent 是能自己决定下一步的程序。\n"
    old.write_text(body, encoding="utf-8")
    db = tmp_path / "app.db"
    out = tmp_path / "chunks.json"

    assert main([str(old), "--db", str(db)]) == 0
    old.unlink()
    new.write_text(body, encoding="utf-8")
    assert main([str(new), "--db", str(db)]) == 0
    assert (
        main([str(new), "--db", str(db), "--emit-chunks", "--out", str(out)]) == 0
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert all(chunk["id"].startswith("old-v1-") for chunk in payload["chunks"])


def test_emit_chunks_after_rename_then_update_keeps_material_id(tmp_path: Path) -> None:
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    old.write_text("# Agent\n\nAgent 是能自己决定下一步的程序。\n", encoding="utf-8")
    db = tmp_path / "app.db"
    out = tmp_path / "chunks.json"

    assert main([str(old), "--db", str(db)]) == 0
    old.unlink()
    new.write_text("# Agent\n\nAgent 是能自己决定下一步的程序。\n", encoding="utf-8")
    assert main([str(new), "--db", str(db)]) == 0

    new.write_text(
        "# Agent\n\nAgent 是能自己决定下一步的程序。\n\n工具调用让模型调用外部工具。\n",
        encoding="utf-8",
    )
    assert (
        main([str(new), "--db", str(db), "--emit-chunks", "--out", str(out)]) == 0
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert all(chunk["id"].startswith("old-v2-") for chunk in payload["chunks"])


def test_html_table_splits_by_row_groups(tmp_path: Path) -> None:
    rows = "".join(
        f"<tr><td>概念{i}</td><td>这是第 {i} 行的说明文字，用来把表格撑到超过子块上限</td></tr>"
        for i in range(1, 41)
    )
    html = (
        "<html><body><table>"
        "<tr><th>名称</th><th>说明</th></tr>"
        f"{rows}</table></body></html>"
    )
    path = tmp_path / "table.html"
    path.write_text(html, encoding="utf-8")

    chunks = chunk_material(parse_material(path))
    tables = [
        chunk
        for chunk in chunks
        if chunk.level == "child" and chunk.text.startswith("|")
    ]
    assert len(tables) > 1
    for chunk in tables:
        lines = chunk.text.splitlines()
        assert lines[0] == "| 名称 | 说明 |"
        assert lines[1] == "| --- | --- |"
        assert "table_split" in chunk.flags
