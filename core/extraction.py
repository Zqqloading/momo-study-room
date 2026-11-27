"""父块 → 概念候选（KB-23）。

不直接联网：调用方注入 ``JsonScorer``（BFF 组装 DeepSeek 适配器）。
硬门槛丢弃，软门槛标 flag；前置只连已存在或同批候选。
单父块失败重试一次，仍失败记 failure 并继续。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Sequence

from .ingestion import Chunk
from .ports import JsonScorer

MAX_CONCEPTS_PER_PARENT = 3
PLAIN_DEF_MAX = 60
BOILERPLATE = ("本段介绍", "本文主要讲", "本节介绍", "综上所述", "总的来说")


class ExtractionError(ValueError):
    """模型输出无法解析或不符合抽取契约。"""


@dataclass(frozen=True, slots=True)
class ExistingConcept:
    id: str
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    name: str
    aliases: tuple[str, ...]
    plain_def: str
    prerequisites: tuple[str, ...]
    prerequisite_names: tuple[str, ...]
    difficulty: int
    source_url: str
    source_excerpt: str
    chunk_id: str
    material_path: str
    flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "aliases": list(self.aliases),
            "plain_def": self.plain_def,
            "prerequisites": list(self.prerequisites),
            "prerequisite_names": list(self.prerequisite_names),
            "difficulty": self.difficulty,
            "source_url": self.source_url,
            "source_excerpt": self.source_excerpt,
            "chunk_id": self.chunk_id,
            "material_path": self.material_path,
            "flags": list(self.flags),
        }


@dataclass(frozen=True, slots=True)
class ExtractionFailure:
    chunk_id: str
    error: str

    def to_dict(self) -> dict[str, str]:
        return {"chunk_id": self.chunk_id, "error": self.error}


@dataclass(frozen=True, slots=True)
class ExtractionReport:
    candidates: tuple[Candidate, ...]
    warnings: tuple[str, ...]
    failures: tuple[ExtractionFailure, ...]
    discarded: int = 0


@dataclass(frozen=True, slots=True)
class _Draft:
    name: str
    aliases: tuple[str, ...]
    plain_def: str
    prerequisite_names: tuple[str, ...]
    difficulty: int
    source_excerpt: str
    chunk_id: str
    flags: tuple[str, ...]


_SYSTEM_PROMPT = """你是 agent 理论的概念抽取器。只输出 JSON 对象，不要 Markdown 代码围栏。
每个父块最多抽 3 个概念。字段：
- name：术语名（不要写句子）
- aliases：别名数组，可以为空
- plain_def：大白话定义，最多 60 个字，不要写“本段介绍/本文主要讲”
- prerequisites：前置概念名数组，只能从“已有概念”或本次输出里选
- difficulty：1-3 的整数
- source_excerpt：从父块正文逐字截取的短句，10-80 字
返回格式：{"concepts": [{"name": "...", "aliases": [], "plain_def": "...", "prerequisites": [], "difficulty": 1, "source_excerpt": "..."}]}"""


class Extractor:
    def __init__(self, scorer: JsonScorer) -> None:
        self._scorer = scorer

    async def extract(
        self,
        parents: Sequence[Chunk],
        *,
        source_url: str,
        material_path: str,
        existing: Sequence[ExistingConcept] = (),
    ) -> ExtractionReport:
        known = _known_names(existing)
        drafts: list[_Draft] = []
        warnings: list[str] = []
        failures: list[ExtractionFailure] = []
        discarded = 0
        used_names = set(known)

        for parent in parents:
            if parent.level != "parent":
                continue
            raw_candidates, error = await self._extract_parent(parent, existing)
            if error is not None:
                failures.append(ExtractionFailure(chunk_id=parent.id, error=error))
                continue
            if len(raw_candidates) > MAX_CONCEPTS_PER_PARENT:
                warnings.append(
                    f"{parent.id}: 返回 {len(raw_candidates)} 个概念，只保留前 {MAX_CONCEPTS_PER_PARENT} 个"
                )
                raw_candidates = raw_candidates[:MAX_CONCEPTS_PER_PARENT]

            for raw in raw_candidates:
                draft, notes = _validate(raw, parent, used_names)
                warnings.extend(f"{parent.id}: {note}" for note in notes)
                if draft is None:
                    discarded += 1
                    continue
                used_names.add(_norm(draft.name))
                used_names.update(_norm(alias) for alias in draft.aliases)
                drafts.append(draft)

        candidates = _resolve(
            drafts, known, existing, warnings, source_url=source_url, material_path=material_path
        )
        return ExtractionReport(
            candidates=tuple(candidates),
            warnings=tuple(warnings),
            failures=tuple(failures),
            discarded=discarded,
        )

    async def _extract_parent(
        self, parent: Chunk, existing: Sequence[ExistingConcept]
    ) -> tuple[list[dict[str, object]], str | None]:
        prompt = _user_prompt(parent, existing)
        last_error = "未知错误"
        for _attempt in range(2):
            try:
                raw = await self._scorer.grade(_SYSTEM_PROMPT, prompt)
                return _parse_candidates(raw), None
            except Exception as exc:  # provider/JSON/形状错误都按单块失败处理
                last_error = f"{type(exc).__name__}: {exc}"
        return [], last_error


def _user_prompt(parent: Chunk, existing: Sequence[ExistingConcept]) -> str:
    names = sorted({concept.name for concept in existing})
    known = "、".join(names) if names else "（无）"
    return (
        f"已有概念（不要重复）：{known}\n"
        f"父块标题：{parent.heading_path or '（无标题）'}\n"
        f"父块正文：\n{parent.text}\n\n"
        "只输出一个 JSON 对象。"
    )


def _parse_candidates(raw: str) -> list[dict[str, object]]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ExtractionError("模型没有返回 JSON 对象")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"JSON 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ExtractionError("JSON 顶层必须是对象")
    items = data.get("concepts")
    if not isinstance(items, list):
        raise ExtractionError("缺少 concepts 数组")
    return [item for item in items if isinstance(item, dict)]


def _validate(
    raw: dict[str, object], parent: Chunk, used_names: set[str]
) -> tuple[_Draft | None, list[str]]:
    notes: list[str] = []
    name = _text(raw.get("name"))
    plain_def = _text(raw.get("plain_def"))
    excerpt = _text(raw.get("source_excerpt"))
    difficulty = raw.get("difficulty")

    if not name or not plain_def or not excerpt:
        return None, ["丢弃：缺少 name/plain_def/source_excerpt"]
    if not isinstance(difficulty, int) or isinstance(difficulty, bool) or not 1 <= difficulty <= 3:
        return None, [f"丢弃 {name}：difficulty 必须是 1-3"]
    if len(plain_def) > PLAIN_DEF_MAX:
        return None, [f"丢弃 {name}：plain_def 超过 {PLAIN_DEF_MAX} 字"]
    if any(phrase in plain_def for phrase in BOILERPLATE):
        return None, [f"丢弃 {name}：plain_def 含套话"]
    if _norm(excerpt) not in _norm(parent.text):
        return None, [f"丢弃 {name}：source_excerpt 不在父块原文"]

    aliases = tuple(
        alias for alias in (_text(item) for item in _as_list(raw.get("aliases"))) if alias
    )
    if _norm(name) in used_names or any(_norm(alias) in used_names for alias in aliases):
        return None, [f"丢弃 {name}：名称/别名与已有概念或本批候选重复"]

    prerequisites = tuple(
        item for item in (_text(value) for value in _as_list(raw.get("prerequisites"))) if item
    )

    flags: list[str] = []
    if len(name) > 30 or re.search(r"[，。！？；,.;!?]", name):
        flags.append("name_not_term")
    if len(_norm(excerpt)) < 10:
        flags.append("short_excerpt")

    return (
        _Draft(
            name=name,
            aliases=aliases,
            plain_def=plain_def,
            prerequisite_names=prerequisites,
            difficulty=int(difficulty),
            source_excerpt=excerpt,
            chunk_id=parent.id,
            flags=tuple(flags),
        ),
        notes,
    )


def _resolve(
    drafts: list[_Draft],
    known: dict[str, str],
    existing: Sequence[ExistingConcept],
    warnings: list[str],
    *,
    source_url: str,
    material_path: str,
) -> list[Candidate]:
    by_id = {concept.id: concept for concept in existing}
    batch_ids = _allocate_ids(drafts, known, by_id)

    mapping = dict(known)
    for draft, concept_id in zip(drafts, batch_ids):
        mapping.setdefault(_norm(draft.name), concept_id)
        for alias in draft.aliases:
            mapping.setdefault(_norm(alias), concept_id)

    candidates: list[Candidate] = []
    for draft, concept_id in zip(drafts, batch_ids):
        resolved: list[str] = []
        flags = list(draft.flags)
        for prerequisite in draft.prerequisite_names:
            target = mapping.get(_norm(prerequisite))
            if target is None:
                warnings.append(f"{draft.chunk_id}: {draft.name} 的前置 {prerequisite} 未找到，已丢弃")
                if "prerequisite_dropped" not in flags:
                    flags.append("prerequisite_dropped")
                continue
            if target == concept_id:
                warnings.append(f"{draft.chunk_id}: {draft.name} 的前置指向自己，已丢弃")
                if "prerequisite_dropped" not in flags:
                    flags.append("prerequisite_dropped")
                continue
            if target not in resolved:
                resolved.append(target)

        candidates.append(
            Candidate(
                id=concept_id,
                name=draft.name,
                aliases=draft.aliases,
                plain_def=draft.plain_def,
                prerequisites=tuple(resolved),
                prerequisite_names=draft.prerequisite_names,
                difficulty=draft.difficulty,
                source_url=source_url,
                source_excerpt=draft.source_excerpt,
                chunk_id=draft.chunk_id,
                material_path=material_path,
                flags=tuple(flags),
            )
        )
    return candidates


def _allocate_ids(
    drafts: list[_Draft], known: dict[str, str], by_id: dict[str, ExistingConcept]
) -> list[str]:
    used = set(known.values()) | set(by_id)
    ids: list[str] = []
    for draft in drafts:
        base = _slug(draft.name)
        candidate_id = base
        suffix = 2
        while candidate_id in used:
            candidate_id = f"{base}-{suffix}"
            suffix += 1
        used.add(candidate_id)
        ids.append(candidate_id)
    return ids


def _known_names(existing: Sequence[ExistingConcept]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for concept in existing:
        mapping.setdefault(_norm(concept.name), concept.id)
        mapping.setdefault(_norm(concept.id), concept.id)
        for alias in concept.aliases:
            mapping.setdefault(_norm(alias), concept.id)
    return mapping


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _slug(text: str) -> str:
    slug = re.sub(r"[^\w\-]+", "-", text.strip().lower(), flags=re.UNICODE).strip("-")
    return slug or "concept"
