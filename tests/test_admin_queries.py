from __future__ import annotations

from pathlib import Path

from core.admin_queries import (
    concept_detail,
    conversation_detail,
    health,
    material_detail,
    question_detail,
    search,
    session_detail,
)
from core.concepts import Concept, Source
from core.db import connect, init_schema
from core.models import ConceptState
from core.store import Store


def make_store() -> Store:
    conn = connect(":memory:")
    init_schema(conn)
    return Store(conn)


def make_concepts() -> list[Concept]:
    return [
        Concept(
            id="agent",
            name="Agent",
            aliases=("智能体",),
            plain_def="能自己决定下一步做什么的系统。",
            difficulty=1,
            prerequisites=(),
            source=Source(
                url="local://materials/m.md",
                excerpt="Agent 会自己决定下一步。",
                material="materials/m.md",
            ),
        ),
        Concept(
            id="workflow",
            name="Workflow",
            aliases=(),
            plain_def="人把步骤排好。",
            difficulty=1,
            prerequisites=("agent",),
            source=Source(
                url="local://materials/m.md",
                excerpt="Workflow 的步骤是人排的。",
                material="materials/m.md",
            ),
        ),
    ]


def seed(store: Store) -> None:
    store.upsert_material(
        material_id="m",
        title="Agent 材料",
        path="materials/m.md",
        format="md",
        content_hash="h2",
        version=2,
        added_at="2026-11-25T00:00:00",
        status="active",
        source_url="local://materials/m.md",
        tags_json=None,
    )
    store.insert_chunks(
        [
            {
                "id": "m-v1-parent-001",
                "material_id": "m",
                "material_version": 1,
                "parent_id": None,
                "level": "parent",
                "heading_path": "Agent",
                "text": "旧版 Agent 段落",
                "content_hash": "p1",
                "token_count": 10,
                "ordinal": 1,
                "source_url": "local://materials/m.md",
            },
            {
                "id": "m-v1-child-002",
                "material_id": "m",
                "material_version": 1,
                "parent_id": "m-v1-parent-001",
                "level": "child",
                "heading_path": "Agent > 旧版",
                "text": "旧版 Agent 子段",
                "content_hash": "c1",
                "token_count": 10,
                "ordinal": 2,
                "source_url": "local://materials/m.md",
            },
            {
                "id": "m-v2-parent-001",
                "material_id": "m",
                "material_version": 2,
                "parent_id": None,
                "level": "parent",
                "heading_path": "Agent",
                "text": "新版 Agent 段落",
                "content_hash": "p2",
                "token_count": 10,
                "ordinal": 1,
                "source_url": "local://materials/m.md",
            },
            {
                "id": "m-v2-child-002",
                "material_id": "m",
                "material_version": 2,
                "parent_id": "m-v2-parent-001",
                "level": "child",
                "heading_path": "Agent > 定义",
                "text": "Agent 会自己决定下一步。",
                "content_hash": "c2",
                "token_count": 10,
                "ordinal": 2,
                "source_url": "local://materials/m.md",
            },
            {
                "id": "m-v2-child-003",
                "material_id": "m",
                "material_version": 2,
                "parent_id": "m-v2-parent-001",
                "level": "child",
                "heading_path": "Agent > 边界",
                "text": "Agent 和工作流的边界。",
                "content_hash": "c3",
                "token_count": 10,
                "ordinal": 3,
                "source_url": "local://materials/m.md",
            },
        ]
    )
    store.upsert_concept_source(
        concept_id="agent",
        chunk_id="m-v1-child-002",
        excerpt="旧版 Agent 子段",
        is_primary=False,
    )
    store.upsert_concept_source(
        concept_id="agent",
        chunk_id="m-v2-child-002",
        excerpt="Agent 会自己决定下一步。",
        is_primary=True,
    )
    store.upsert_concept(ConceptState(id="agent", mastery=2, status="active"))
    store.upsert_concept(ConceptState(id="workflow", mastery=1, status="active"))
    store.import_question_bank(
        [
            {
                "id": "bank-1",
                "concept_id": "agent",
                "kind": "recall",
                "question_text": "Agent 是什么？",
                "rubric_json": {"levels": []},
                "source_url": "local://materials/m.md",
                "source_excerpt": "Agent 会自己决定下一步。",
            }
        ]
    )
    store.start_agent_session(
        session_id="s1",
        kind="daily",
        date="2026-11-26",
        started_at="2026-11-26T10:00:00",
        concept_id="agent",
        input_mode="text",
    )
    bank_q = store.add_question(
        session_id="s1",
        question_bank_id="bank-1",
        concept_id="agent",
        role="new",
        kind="recall",
        text="Agent 是什么？",
        rubric_json={"levels": []},
        source_url="local://materials/m.md",
        source_excerpt="Agent 会自己决定下一步。",
        created_at="2026-11-26T10:00:00",
    )
    store.save_answer(bank_q, text="自己决定下一步", score=70, feedback="方向对")
    gen_q = store.add_question(
        session_id="s1",
        question_bank_id=None,
        concept_id="agent",
        role="new",
        kind="recall",
        question_type="concept",
        text="用自己的话说 Agent。",
        rubric_json={"levels": []},
        source_url="local://materials/m.md",
        source_excerpt="Agent 会自己决定下一步。",
        source_chunk_id="m-v2-child-002",
        generation_meta_json={"origin": "generated", "model": "fake"},
        created_at="2026-11-26T10:01:00",
    )
    store.save_answer(gen_q, text="会自己选下一步", score=80, feedback="好")
    old_q = store.add_question(
        session_id="s1",
        question_bank_id=None,
        concept_id="agent",
        role="review",
        kind="recall",
        text="旧版问题",
        rubric_json={"levels": []},
        source_url="local://materials/m.md",
        source_excerpt="旧版 Agent 子段",
        source_chunk_id="m-v1-child-002",
        created_at="2026-11-26T10:02:00",
    )
    store.save_answer(old_q, text="旧版回答", score=60, feedback="旧")
    store.add_session_note(
        session_id="s1",
        question_id=gen_q,
        mode="probe",
        input_text="举例",
        output_text="比如点外卖",
        created_at="2026-11-26T10:03:00",
    )
    store.create_conversation(
        conversation_id="conv", created_at="2026-11-26T11:00:00", title="Agent 对话"
    )
    store.append_conversation_message(
        conversation_id="conv",
        role="user",
        text="Agent 是什么？",
        created_at="2026-11-26T11:00:01",
    )
    store.append_conversation_message(
        conversation_id="conv",
        role="assistant",
        text="材料里说 Agent 自己决定下一步。",
        created_at="2026-11-26T11:00:02",
        sources=[
            {
                "index": 1,
                "title": "m.md",
                "url": "local://materials/m.md",
                "excerpt": "Agent 会自己决定下一步。",
                "kind": "material",
            },
            {
                "index": 2,
                "title": "网页",
                "url": "https://example.com/agent",
                "excerpt": "外部解释",
                "kind": "web",
                "domain": "example.com",
            },
        ],
    )


def test_search_groups_entities() -> None:
    store = make_store()
    try:
        seed(store)
        result = search(store.conn, make_concepts(), "Agent")
        assert result["counts"]["materials"] == 1
        assert result["counts"]["concepts"] == 1
        assert result["counts"]["questions"] >= 2
        assert result["counts"]["sessions"] >= 1
        assert any(
            item["type"] == "conversation"
            for item in result["groups"]["sessions"]
        )
    finally:
        store.close()


def test_material_detail_current_and_history() -> None:
    store = make_store()
    try:
        seed(store)
        current = material_detail(
            store.conn,
            make_concepts(),
            "m",
            db_path=Path("data/test.db"),
            content_dir=Path("."),
        )
        assert current is not None
        assert current["counts"]["chunks"] == 3
        assert current["counts"]["concepts"] == 1
        assert current["counts"]["bank_questions"] == 1
        assert current["counts"]["session_questions"] == 2
        assert current["counts"]["provenance"]["chunk"] == 1
        assert current["counts"]["provenance"]["url"] == 2
        assert current["counts"]["citations"] == 1
        assert all(
            item["material_version"] == 2
            for item in current["session_questions"]
            if item["provenance"]["level"] == "chunk"
        )

        history = material_detail(
            store.conn,
            make_concepts(),
            "m",
            history=True,
            db_path=Path("data/test.db"),
            content_dir=Path("."),
        )
        assert history is not None
        assert history["counts"]["chunks"] == 5
        assert history["counts"]["session_questions"] == 3
        assert {item["material_version"] for item in history["session_questions"]} == {
            1,
            2,
            None,
        }
    finally:
        store.close()


def test_concept_detail_links_both_ways() -> None:
    store = make_store()
    try:
        seed(store)
        detail = concept_detail(
            store.conn,
            make_concepts(),
            "agent",
            db_path=Path("data/test.db"),
            content_dir=Path("."),
        )
        assert detail is not None
        assert detail["counts"]["sources"] == 2
        assert detail["counts"]["bank_questions"] == 1
        assert detail["counts"]["session_questions"] == 3
        assert detail["counts"]["dependents"] == 1
        assert detail["latest_assessment"]["avg_score"] == 70
        assert detail["state"]["mastery"] == 2
    finally:
        store.close()


def test_question_detail_bank_and_generated() -> None:
    store = make_store()
    try:
        seed(store)
        bank = question_detail(
            store.conn,
            make_concepts(),
            bank_id="bank-1",
            db_path=Path("data/test.db"),
            content_dir=Path("."),
        )
        assert bank is not None
        assert bank["origin"]["kind"] == "bank"
        assert bank["provenance"]["level"] == "url"
        assert bank["counts"]["usage"] == 1

        generated_id = store.conn.execute(
            "SELECT id FROM session_questions WHERE source_chunk_id = ?",
            ("m-v2-child-002",),
        ).fetchone()[0]
        generated = question_detail(
            store.conn,
            make_concepts(),
            session_question_id=int(generated_id),
            db_path=Path("data/test.db"),
            content_dir=Path("."),
        )
        assert generated is not None
        assert generated["origin"]["kind"] == "generated"
        assert generated["provenance"]["level"] == "chunk"
        assert generated["provenance"]["material_version"] == 2
    finally:
        store.close()


def test_session_detail_and_conversation_citations() -> None:
    store = make_store()
    try:
        seed(store)
        session = session_detail(store.conn, make_concepts(), "s1")
        assert session is not None
        assert session["counts"] == {"questions": 3, "scored": 3, "notes": 1}
        assert session["questions"][0]["provenance"]["level"] == "url"
        assert session["questions"][1]["provenance"]["level"] == "chunk"

        conversation = conversation_detail(store.conn, "conv")
        assert conversation is not None
        assert conversation["counts"] == {
            "messages": 2,
            "material_sources": 1,
            "web_sources": 1,
        }
    finally:
        store.close()


def test_health_reports_pipeline_and_index() -> None:
    store = make_store()
    try:
        seed(store)
        run_id = store.start_pipeline_run("ingest", "materials/m.md")
        store.finish_pipeline_run(run_id, "failed", error="boom")
        report = health(
            store.conn,
            db_path=Path("data/test.db"),
            provider={"fake": False, "modes": {"llm": "real"}, "notes": []},
            embedding_model="fake",
            embedding_dim=3,
        )
        assert report["db"]["version"] == 8
        assert any(item["code"] == "pipeline_ingest" for item in report["red"])
        assert report["yellow"]
        assert report["index"]["missing_embeddings"] == 2
    finally:
        store.close()


def test_queries_do_not_change_rows() -> None:
    store = make_store()
    try:
        seed(store)
        before = store.conn.total_changes
        concepts = make_concepts()
        search(store.conn, concepts, "Agent")
        material_detail(
            store.conn,
            concepts,
            "m",
            db_path=Path("data/test.db"),
            content_dir=Path("."),
        )
        material_detail(
            store.conn,
            concepts,
            "m",
            history=True,
            db_path=Path("data/test.db"),
            content_dir=Path("."),
        )
        concept_detail(
            store.conn,
            concepts,
            "agent",
            db_path=Path("data/test.db"),
            content_dir=Path("."),
        )
        question_detail(
            store.conn,
            concepts,
            bank_id="bank-1",
            db_path=Path("data/test.db"),
            content_dir=Path("."),
        )
        session_detail(store.conn, concepts, "s1")
        conversation_detail(store.conn, "conv")
        health(store.conn, db_path=Path("data/test.db"))
        assert store.conn.total_changes == before
    finally:
        store.close()


def test_repair_commands_target_the_given_database() -> None:
    store = make_store()
    try:
        seed(store)
        detail = material_detail(
            store.conn,
            make_concepts(),
            "m",
            db_path=Path("data/app-v5.db"),
            content_dir=Path("."),
        )
        assert detail is not None
        commands = [
            step["command"]
            for step in detail["repair"]["steps"]
            if step["command"]
        ]
        assert commands
        assert all("--db \"data/app-v5.db\"" in command for command in commands if "python -m core" in command)
        assert detail["repair"]["steps"][4]["skip_if"]
    finally:
        store.close()
