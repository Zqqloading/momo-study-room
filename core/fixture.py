"""第一片 fixture：3 个 active 概念与题库的幂等导入。

fixture 只用于流程验证；真实内容归知识库。重复导入不重置 mastery，
也不把用户后来改成的 skipped/known 重新拉回 active。
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .concepts import load_concepts, sync_runtime
from .store import Store


def load_fixture(store: Store, concepts_path: str | Path, bank_path: str | Path) -> None:
    concepts = load_concepts(concepts_path)

    payload = json.loads(Path(bank_path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("题库 JSON 顶层必须是列表")

    store.import_question_bank(payload)
    sync_runtime(store, concepts)

    for concept in concepts:
        state = store.concept_state(concept.id)
        if state is not None and state.status == "proposed":
            store.upsert_concept(replace(state, status="active"))
