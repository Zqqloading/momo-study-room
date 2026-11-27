"""公开 demo 内容包：首次启动把 `demo/` 里的材料与概念/题库装进空库。

`demo/` 是仓库自带的可跑内容，走的是和 `core.ingest` 一样的解析与切块；
只在库内还没有任何材料时导入，避免覆盖用户自己的内容。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .concepts import Concept, load_concepts, sync_runtime
from .ingestion import chunk_material, material_id, parse_material
from .store import Store


def load_demo(store: Store, demo_dir: Path) -> list[Concept]:
    concepts = load_concepts(demo_dir / "concepts.yaml")
    bank_path = demo_dir / "seeds" / "question_bank.json"

    payload = json.loads(bank_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("demo 题库 JSON 顶层必须是列表")

    store.import_question_bank(payload)
    sync_runtime(store, concepts)
    for concept in concepts:
        state = store.concept_state(concept.id)
        if state is not None and state.status == "proposed":
            store.upsert_concept(replace(state, status="active"))

    _ingest_materials(store, demo_dir)
    _link_sources(store, concepts)
    return concepts


def _link_sources(store: Store, concepts: list[Concept]) -> None:
    """把概念出处写进 concept_sources，材料详情页与出处回溯才看得到概念。"""
    for concept in concepts:
        material = concept.source.material
        if not material:
            continue
        chunks = store.material_chunks(material_id(Path(material).name))
        if not chunks:
            continue
        excerpt = concept.source.excerpt.strip()
        match = next(
            (chunk for chunk in chunks if excerpt and excerpt in chunk["text"]), None
        ) or next(
            (chunk for chunk in chunks if chunk["level"] == "parent"), chunks[0]
        )
        store.upsert_concept_source(
            concept_id=concept.id,
            chunk_id=match["id"],
            excerpt=excerpt or str(match["text"])[:80],
        )


def _ingest_materials(store: Store, demo_dir: Path) -> None:
    materials_dir = demo_dir / "materials"
    if not materials_dir.is_dir() or store.has_materials():
        return

    root = demo_dir.parent
    files = sorted(materials_dir.glob("*.md")) + sorted(materials_dir.glob("*.html"))
    for path in files:
        rel = path.relative_to(root).as_posix()
        material = replace(parse_material(path), path=rel)
        chunks = chunk_material(material, version=1, mid=material_id(rel))
        with store.transaction():
            store.upsert_material(
                material_id=material_id(rel),
                title=material.title,
                path=material.path,
                format=material.format,
                content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                version=1,
                added_at=datetime.now().isoformat(timespec="seconds"),
                status="active",
                source_url=material.source_url or f"local://{material.path}",
                tags_json=(
                    json.dumps(list(material.tags), ensure_ascii=False)
                    if material.tags
                    else None
                ),
            )
            store.insert_chunks([chunk.to_dict() for chunk in chunks])
    store.rebuild_fts()
