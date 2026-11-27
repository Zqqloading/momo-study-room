from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace

from fastapi.testclient import TestClient

from bff.config import load_settings
from bff.main import create_app
from core.db import connect, init_schema
from core.store import Store


def make_env(tmp_path) -> dict[str, str]:
    return {
        "PROVIDER_MODE": "fake",
        "DB_PATH": str(tmp_path / "app.db"),
        "DATA_DIR": str(tmp_path / "data"),
        "CONTENT_DIR": str(tmp_path),
    }


def seed(tmp_path) -> None:
    store = Store(connect(tmp_path / "app.db"))
    try:
        init_schema(store.conn)
        store.upsert_material(
            material_id="m1",
            title="Fixture 材料",
            path="materials/fixture.md",
            format="md",
            content_hash="h1",
            version=1,
            added_at="2026-11-26T00:00:00",
            status="active",
            source_url="fixture://agent-loop",
            tags_json=None,
        )
        store.insert_chunks(
            [
                {
                    "id": "m1-v1-parent-001",
                    "material_id": "m1",
                    "material_version": 1,
                    "parent_id": None,
                    "level": "parent",
                    "heading_path": "Agent 循环",
                    "text": "Agent 循环",
                    "content_hash": "p1",
                    "token_count": 5,
                    "ordinal": 1,
                    "source_url": "fixture://agent-loop",
                },
                {
                    "id": "m1-v1-child-002",
                    "material_id": "m1",
                    "material_version": 1,
                    "parent_id": "m1-v1-parent-001",
                    "level": "child",
                    "heading_path": "Agent 循环 > 步骤",
                    "text": "观察、决策、行动。",
                    "content_hash": "c1",
                    "token_count": 5,
                    "ordinal": 2,
                    "source_url": "fixture://agent-loop",
                },
            ]
        )
        store.upsert_concept_source(
            concept_id="agent-loop",
            chunk_id="m1-v1-child-002",
            excerpt="观察、决策、行动。",
            is_primary=True,
        )
        run_id = store.start_pipeline_run("ingest", "materials/fixture.md")
        store.finish_pipeline_run(run_id, "succeeded", {"fts_rows": 1})
        store.start_agent_session(
            session_id="s1",
            kind="daily",
            date="2026-11-26",
            started_at="2026-11-26T10:00:00",
            concept_id="agent-loop",
        )
        store.add_question(
            session_id="s1",
            question_bank_id=None,
            concept_id="agent-loop",
            role="new",
            kind="recall",
            text="用自己的话说 Agent 循环。",
            rubric_json={"levels": []},
            source_url="fixture://agent-loop",
            source_excerpt="观察、决策、行动。",
            source_chunk_id="m1-v1-child-002",
            generation_meta_json={"origin": "generated"},
            created_at="2026-11-26T10:00:00",
        )
        store.create_conversation(
            conversation_id="conv",
            created_at="2026-11-26T11:00:00",
            title="Fixture 对话",
        )
        store.append_conversation_message(
            conversation_id="conv",
            role="assistant",
            text="材料里说 Agent 循环是观察、决策、行动。",
            created_at="2026-11-26T11:00:01",
            sources=[
                {
                    "index": 1,
                    "title": "fixture",
                    "url": "fixture://agent-loop",
                    "excerpt": "观察、决策、行动。",
                    "kind": "material",
                }
            ],
        )
    finally:
        store.close()


def test_admin_endpoints_read_only(tmp_path) -> None:
    seed(tmp_path)
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client, closing(
        sqlite3.connect(tmp_path / "app.db")
    ) as watcher:
        before = watcher.execute("PRAGMA data_version").fetchone()[0]

        health = client.get("/api/admin/health")
        assert health.status_code == 200
        assert health.json()["db"]["version"] == 8
        assert any(
            item["code"] == "provider_fake" for item in health.json()["red"]
        )

        search = client.get("/api/admin/search", params={"q": "Agent"})
        assert search.status_code == 200
        assert search.json()["counts"]["materials"] >= 1

        material = client.get("/api/admin/material/m1")
        assert material.status_code == 200
        payload = material.json()
        assert payload["counts"]["chunks"] == 2
        assert payload["counts"]["session_questions"] == 1
        assert payload["repair"]["steps"]

        concept = client.get("/api/admin/concept/agent-loop")
        assert concept.status_code == 200
        assert concept.json()["counts"]["bank_questions"] >= 1

        bank = client.get(
            "/api/admin/question", params={"bank_id": "agent-loop-recall-1"}
        )
        assert bank.status_code == 200
        assert bank.json()["origin"]["kind"] == "bank"

        session = client.get("/api/admin/session/s1")
        assert session.status_code == 200
        assert session.json()["counts"]["questions"] == 1

        conversation = client.get("/api/admin/conversation/conv")
        assert conversation.status_code == 200
        assert conversation.json()["counts"]["messages"] == 1

        assert client.get("/api/admin/material/nope").status_code == 404
        assert client.get("/api/admin/question").status_code == 400

        after = watcher.execute("PRAGMA data_version").fetchone()[0]
        assert after == before


def test_task_api_create_get_list(tmp_path) -> None:
    seed(tmp_path)
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        created = client.post(
            "/api/admin/tasks",
            json={"kind": "rebuild", "params": {"fts_only": True}},
        )
        assert created.status_code == 202
        task_id = created.json()["task_id"]
        assert created.json()["status"] == "queued"

        detail = client.get(f"/api/admin/tasks/{task_id}")
        assert detail.status_code == 200
        assert detail.headers["cache-control"] == "no-store"
        payload = detail.json()
        assert payload["kind"] == "rebuild"
        assert payload["status"] == "queued"
        assert payload["params"]["fts_only"] is True

        listing = client.get("/api/admin/tasks")
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        assert listing.json()["data"][0]["task_id"] == task_id
        assert (
            client.get("/api/admin/tasks", params={"ids": task_id})
            .json()["total"]
            == 1
        )
        assert (
            client.get("/api/admin/tasks", params={"sort": "bad"})
            .status_code
            == 400
        )

        duplicate = client.post(
            "/api/admin/tasks",
            json={"kind": "rebuild", "params": {"fts_only": True}},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["task_id"] == task_id

        bad = client.post(
            "/api/admin/tasks",
            json={"kind": "ingest", "params": {"path": "docs/x.md"}},
        )
        assert bad.status_code == 400
        assert bad.json()["field"] == "path"

        assert client.get("/api/admin/tasks/nope").status_code == 404


def test_upload_materials(tmp_path) -> None:
    (tmp_path / "materials").mkdir()
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/uploads",
            files={"files": ("note.md", b"# note", "text/markdown")},
        )
        assert response.status_code == 200
        uploaded = response.json()["files"][0]
        assert uploaded["path"] == "materials/inbox/note.md"
        assert (tmp_path / "materials" / "inbox" / "note.md").read_bytes() == (
            b"# note"
        )

        duplicate = client.post(
            "/api/admin/uploads",
            files={"files": ("note.md", b"# note", "text/markdown")},
        )
        assert duplicate.status_code == 409

        bad_suffix = client.post(
            "/api/admin/uploads",
            files={"files": ("note.txt", b"x", "text/plain")},
        )
        assert bad_suffix.status_code == 400

        empty = client.post(
            "/api/admin/uploads",
            files={"files": ("empty.md", b"", "text/markdown")},
        )
        assert empty.status_code == 400

        traversal = client.post(
            "/api/admin/uploads",
            files={"files": ("../evil.md", b"x", "text/markdown")},
        )
        assert traversal.status_code == 200
        assert traversal.json()["files"][0]["path"] == "materials/inbox/evil.md"

        multiple = client.post(
            "/api/admin/uploads",
            files=[
                ("files", ("a.md", b"a", "text/markdown")),
                ("files", ("b.html", b"b", "text/html")),
            ],
        )
        assert multiple.status_code == 200
        assert len(multiple.json()["files"]) == 2


def test_upload_rejects_large_file(tmp_path, monkeypatch) -> None:
    from bff import admin as admin_module

    monkeypatch.setattr(admin_module, "MAX_UPLOAD_BYTES", 4)
    (tmp_path / "materials").mkdir()
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/uploads",
            files={"files": ("big.md", b"12345", "text/markdown")},
        )
    assert response.status_code == 413


def test_scan_materials(tmp_path) -> None:
    (tmp_path / "materials").mkdir()
    (tmp_path / "materials" / "new.md").write_text("# new", encoding="utf-8")
    seed(tmp_path)
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        response = client.get("/api/admin/materials/scan")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert [item["path"] for item in payload["new"]] == ["materials/new.md"]
    assert "m1" in [item["id"] for item in payload["missing"]]
    assert payload["unchanged"] == 0
    assert payload["errors"] == []


def test_admin_routes_are_get_only_except_writes(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    paths = app.openapi()["paths"]
    admin_paths = {
        path: operations
        for path, operations in paths.items()
        if path.startswith("/api/admin")
    }
    assert admin_paths
    assert set(admin_paths["/api/admin/tasks"]) == {"get", "post"}
    assert set(admin_paths["/api/admin/uploads"]) == {"post"}
    for path, operations in admin_paths.items():
        if path in {"/api/admin/tasks", "/api/admin/uploads"}:
            continue
        assert set(operations) == {"get"}, path


def test_learning_page_links_to_admin(tmp_path) -> None:
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        response = client.get("/")
        assert client.get("/admin/").status_code == 200
    assert response.status_code == 200
    assert 'href="/admin/"' in response.text


def test_admin_build_missing_returns_503(tmp_path) -> None:
    (tmp_path / "web").mkdir()
    settings = replace(
        load_settings(make_env(tmp_path)), web_dir=tmp_path / "web"
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/admin/")
    assert response.status_code == 503
    assert "npm run build" in response.text


def test_admin_list_endpoints(tmp_path) -> None:
    seed(tmp_path)
    app = create_app(load_settings(make_env(tmp_path)))
    with TestClient(app) as client:
        materials = client.get(
            "/api/admin/materials", params={"page": 1, "per_page": 1}
        )
        assert materials.status_code == 200
        assert materials.json()["total"] == 1
        assert materials.json()["data"][0]["id"] == "m1"
        assert (
            client.get("/api/admin/materials", params={"status": "missing"})
            .json()["total"]
            == 0
        )
        assert (
            client.get("/api/admin/materials", params={"status": "bad"})
            .status_code
            == 400
        )
        assert (
            client.get("/api/admin/materials", params={"sort": "bad"})
            .status_code
            == 400
        )

        concepts = client.get("/api/admin/concepts", params={"q": "Agent"})
        assert concepts.status_code == 200
        assert any(
            item["id"] == "agent-loop" for item in concepts.json()["data"]
        )
        assert (
            client.get("/api/admin/concepts", params={"mastery": 9})
            .status_code
            == 400
        )
        assert (
            client.get("/api/admin/concepts", params={"ids": "agent-loop"})
            .json()["total"]
            == 1
        )

        bank = client.get(
            "/api/admin/bank-questions", params={"concept_id": "agent-loop"}
        )
        assert bank.status_code == 200
        assert bank.json()["total"] >= 1
        assert (
            client.get("/api/admin/bank-questions", params={"kind": "bad"})
            .status_code
            == 400
        )

        session_questions = client.get(
            "/api/admin/session-questions", params={"session_id": "s1"}
        )
        assert session_questions.json()["total"] == 1
        assert (
            client.get(
                "/api/admin/session-questions", params={"min_score": 101}
            ).status_code
            == 400
        )

        sessions = client.get("/api/admin/sessions", params={"status": "active"})
        assert sessions.json()["total"] == 1
        assert (
            client.get("/api/admin/sessions", params={"q": "Agent"})
            .json()["total"]
            >= 1
        )
        assert (
            client.get("/api/admin/sessions", params={"kind": "bad"})
            .status_code
            == 400
        )

        conversations = client.get(
            "/api/admin/conversations", params={"q": "Fixture"}
        )
        assert conversations.json()["total"] == 1
        assert (
            client.get("/api/admin/conversations", params={"ids": "conv"})
            .json()["total"]
            == 1
        )

        pipelines = client.get(
            "/api/admin/pipeline-runs", params={"kind": "ingest"}
        )
        assert pipelines.status_code == 200
        assert pipelines.json()["total"] == 1
        assert (
            client.get("/api/admin/pipeline-runs", params={"kind": "bad"})
            .status_code
            == 400
        )
