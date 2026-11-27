from __future__ import annotations

from pathlib import Path

from core.admin_queries import concept_detail, health, material_detail
from core.db import connect, init_schema
from core.demo import load_demo
from core.store import Store

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"


def test_demo_content_impact_samples(tmp_path) -> None:
    """用仓库自带的 demo 内容验收管理后台的只读查询口径。"""
    db_path = tmp_path / "app.db"
    store = Store(connect(db_path))
    init_schema(store.conn)
    conn = store.conn
    concepts = load_demo(store, DEMO)
    try:
        agent = material_detail(
            conn, concepts, "agent-工具调用基础", db_path=db_path, content_dir=DEMO
        )
        assert agent is not None
        assert agent["versions"][0]["version"] == 1
        assert agent["counts"]["chunks"] == 8
        assert agent["counts"]["parents"] == 2
        assert agent["counts"]["children"] == 6
        assert agent["counts"]["concepts"] == 3
        assert agent["counts"]["bank_questions"] == 13
        assert agent["counts"]["session_questions"] == 0
        assert agent["counts"]["provenance"]["url"] > 0

        rag = material_detail(
            conn, concepts, "rag-检索与出处", db_path=db_path, content_dir=DEMO
        )
        assert rag is not None
        assert rag["counts"]["chunks"] == 6
        assert rag["counts"]["parents"] == 1
        assert rag["counts"]["children"] == 5
        assert rag["counts"]["concepts"] == 3
        assert rag["counts"]["bank_questions"] == 15

        concept = concept_detail(
            conn, concepts, "切块", db_path=db_path, content_dir=DEMO
        )
        assert concept is not None
        assert concept["counts"]["bank_questions"] == 5
        assert concept["counts"]["sources"] == 1
        assert concept["counts"]["dependents"] == 2
        assert concept["state"]["mastery"] == 0

        report = health(
            conn,
            db_path=db_path,
            provider={"fake": False, "modes": {"llm": "real"}, "notes": []},
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
        )
        assert report["db"]["version"] == 8
        assert report["counts"]["materials"] == 2
        assert report["counts"]["chunks"] == 14
        assert report["counts"]["concepts"] == 6
        assert report["counts"]["bank_questions"] == 28

        for detail in (agent, rag, concept):
            commands = [
                step["command"]
                for step in detail["repair"]["steps"]
                if step["command"] and "python -m core" in step["command"]
            ]
            assert commands
            assert all(f'--db "{db_path.as_posix()}"' in command for command in commands)
    finally:
        store.close()
