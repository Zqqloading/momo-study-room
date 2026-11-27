"""concepts.yaml 的加载、校验与运行时同步。

YAML 是概念内容的唯一真相源；SQLite 只存 mastery/status/last_seen/review_due_at。
这里不写库内容字段，只负责把 YAML 的增删映射成运行时状态。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from .models import ConceptState
from .store import Store


class ConceptsError(ValueError):
    """YAML 不合规；错误信息必须指出坏节点。"""


@dataclass(frozen=True, slots=True)
class Source:
    url: str
    excerpt: str
    material: str | None = None


@dataclass(frozen=True, slots=True)
class Concept:
    id: str
    name: str
    aliases: tuple[str, ...]
    plain_def: str
    difficulty: int
    prerequisites: tuple[str, ...]
    source: Source


@dataclass(frozen=True, slots=True)
class SyncReport:
    added: tuple[str, ...] = ()
    orphaned: tuple[str, ...] = ()
    restored: tuple[str, ...] = ()


def _text(value: Any, field: str, node: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConceptsError(f"节点 {node} 的 {field} 必须是非空字符串")
    return value.strip()


def _string_list(value: Any, field: str, node: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ConceptsError(f"节点 {node} 的 {field} 必须是字符串列表")
    return tuple(item.strip() for item in value if item.strip())


def _parse_item(item: Any) -> Concept:
    if not isinstance(item, dict):
        raise ConceptsError("concepts 里每一行必须是对象")

    node = str(item.get("id") or "?").strip() or "?"
    concept_id = _text(item.get("id"), "id", node)
    name = _text(item.get("name"), "name", concept_id)
    plain_def = _text(item.get("plain_def"), "plain_def", concept_id)

    difficulty = item.get("difficulty")
    if not isinstance(difficulty, int) or isinstance(difficulty, bool) or not 1 <= difficulty <= 3:
        raise ConceptsError(f"节点 {concept_id} 的 difficulty 必须是 1-3")

    source_raw = item.get("source")
    if not isinstance(source_raw, dict):
        raise ConceptsError(f"节点 {concept_id} 缺少 source")
    source = Source(
        url=_text(source_raw.get("url"), "source.url", concept_id),
        excerpt=_text(source_raw.get("excerpt"), "source.excerpt", concept_id),
        material=(
            source_raw.get("material").strip()
            if isinstance(source_raw.get("material"), str) and source_raw["material"].strip()
            else None
        ),
    )

    return Concept(
        id=concept_id,
        name=name,
        aliases=_string_list(item.get("aliases"), "aliases", concept_id),
        plain_def=plain_def,
        difficulty=difficulty,
        prerequisites=_string_list(item.get("prerequisites"), "prerequisites", concept_id),
        source=source,
    )


def _check_graph(concepts: list[Concept]) -> None:
    by_id = {concept.id: concept for concept in concepts}
    for concept in concepts:
        for prerequisite in concept.prerequisites:
            if prerequisite == concept.id:
                raise ConceptsError(f"节点 {concept.id} 不能把自己当前置")
            if prerequisite not in by_id:
                raise ConceptsError(f"节点 {concept.id} 的前置不存在：{prerequisite}")

    state: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> None:
        if state.get(node) == 1:
            cycle = " -> ".join(stack + [node])
            raise ConceptsError(f"前置成环：{cycle}")
        if state.get(node) == 2:
            return
        state[node] = 1
        for prerequisite in by_id[node].prerequisites:
            visit(prerequisite, stack + [node])
        state[node] = 2

    for concept_id in by_id:
        visit(concept_id, [])


def load_concepts(path: str | Path) -> list[Concept]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConceptsError("YAML 顶层必须是对象")

    if raw.get("version") != 1:
        raise ConceptsError("version 必须为 1")

    items = raw.get("concepts")
    if not isinstance(items, list) or not items:
        raise ConceptsError("concepts 必须是非空列表")

    concepts = [_parse_item(item) for item in items]
    ids = [concept.id for concept in concepts]
    duplicates = sorted({concept_id for concept_id in ids if ids.count(concept_id) > 1})
    if duplicates:
        raise ConceptsError(f"id 重复：{', '.join(duplicates)}")

    _check_graph(concepts)
    return concepts


def sync_runtime(store: Store, concepts: list[Concept]) -> SyncReport:
    """把 YAML 的增删映射成 SQLite 运行时状态，不动已有 mastery。"""
    existing = {state.id: state for state in store.concept_states()}
    yaml_ids = {concept.id for concept in concepts}
    added: list[str] = []
    restored: list[str] = []

    with store.transaction():
        for concept in concepts:
            current = existing.get(concept.id)
            if current is None:
                store.upsert_concept(ConceptState(id=concept.id, status="proposed"))
                added.append(concept.id)
            elif current.status == "orphaned":
                store.upsert_concept(
                    replace(current, status=current.prior_status or "proposed", prior_status=None)
                )
                restored.append(concept.id)

        orphaned: list[str] = []
        for concept_id, state in existing.items():
            if concept_id in yaml_ids or state.status == "orphaned":
                continue
            store.upsert_concept(replace(state, status="orphaned", prior_status=state.status))
            orphaned.append(concept_id)

    return SyncReport(
        added=tuple(sorted(added)),
        orphaned=tuple(sorted(orphaned)),
        restored=tuple(sorted(restored)),
    )
