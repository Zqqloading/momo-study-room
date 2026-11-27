"""出题组装根：主出处 + 检索 top5 → 模型 → 解析/校验/修复。

只读本地已确认知识库与 session_questions；不 import 搜索适配器（ADR 0002）。
"""

from __future__ import annotations

from typing import Sequence

from core.concepts import Concept
from core.ports import Embedder, JsonScorer
from core.question_generation import (
    ContextChunk,
    GenerationContext,
    GenerationError,
    GeneratedSet,
    QuestionDraft,
    QuestionGenerator,
    SessionPlan,
    ValidationResult,
    apply_repair,
    build_generation_messages,
    build_repair_messages,
    parse_generation,
    to_generated_question,
    validate_question_set,
)
from core.retrieval import RetrievedChunk
from core.store import Store

from .retrieval import retrieve_concept

PROMPT_VERSION = "qgen-v1"
CONTEXT_MAX_CHARS = 1200


def _plan_concepts(plan: SessionPlan) -> list[Concept]:
    concepts: list[Concept] = []
    for concept in (plan.main_concept, plan.review_concept):
        if concept is not None and all(item.id != concept.id for item in concepts):
            concepts.append(concept)
    return concepts


def _block_key(chunk) -> str:
    return chunk.parent_chunk_id or chunk.chunk_id


async def build_contexts(
    store: Store,
    embedder: Embedder,
    plan: SessionPlan,
    *,
    top_k: int = 5,
) -> dict[str, GenerationContext]:
    contexts: dict[str, GenerationContext] = {}
    for concept in _plan_concepts(plan):
        contexts[concept.id] = await build_context(
            store, embedder, concept, top_k=top_k
        )
    return contexts


async def build_context(
    store: Store,
    embedder: Embedder,
    concept: Concept,
    *,
    top_k: int = 5,
) -> GenerationContext:
    primary = _primary_chunk(store, concept)
    chunks = [primary]
    seen = {_block_key(primary)}

    for hit in await retrieve_concept(store, embedder, concept, top_k=top_k):
        chunk = _retrieval_chunk(store, hit, len(chunks) + 1)
        key = _block_key(chunk)
        if key in seen:
            continue
        seen.add(key)
        chunks.append(chunk)
        if len(chunks) >= top_k + 1:
            break

    return GenerationContext(concept_id=concept.id, chunks=tuple(chunks))


def _primary_chunk(store: Store, concept: Concept) -> ContextChunk:
    source = store.primary_concept_source(concept.id)
    if source is None or not source.get("chunk_id"):
        raise GenerationError(f"概念缺少主出处：{concept.id}")
    chunk_id = str(source["chunk_id"])
    row = store.chunk_with_parent(chunk_id)
    if row is None:
        raise GenerationError(f"概念主出处块不存在：{chunk_id}")

    parent_id = row["parent_chunk_id"]
    if parent_id:
        text = row["parent_text"] or row["child_text"]
        heading = row["parent_heading"] or row["child_heading"]
        url = row["parent_url"] or row["child_url"]
    else:
        text = row["child_text"]
        heading = row["child_heading"]
        url = row["child_url"]

    return ContextChunk(
        ref=1,
        chunk_id=chunk_id,
        parent_chunk_id=str(parent_id) if parent_id else None,
        heading_path=heading,
        text=str(text)[:CONTEXT_MAX_CHARS],
        source_url=str(url or ""),
        origin="primary",
    )


def _retrieval_chunk(
    store: Store, hit: RetrievedChunk, ref: int
) -> ContextChunk:
    row = store.chunk_with_parent(hit.chunk_id)
    heading = None
    if row is not None:
        heading = row["parent_heading"] or row["child_heading"]
    return ContextChunk(
        ref=ref,
        chunk_id=hit.chunk_id,
        parent_chunk_id=hit.parent_chunk_id,
        heading_path=heading,
        text=hit.text[:CONTEXT_MAX_CHARS],
        source_url=hit.source_url,
        origin="retrieval",
    )


class BffQuestionGenerator(QuestionGenerator):
    """DeepSeek（或注入的脚本模型）实现；失败统一抛 ``GenerationError``。"""

    def __init__(
        self,
        store: Store,
        embedder: Embedder,
        llm: JsonScorer,
        *,
        model: str = "deepseek-chat",
        prompt_version: str = PROMPT_VERSION,
        top_k: int = 5,
        previous_limit: int = 10,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._llm = llm
        self._model = model
        self._prompt_version = prompt_version
        self._top_k = top_k
        self._previous_limit = previous_limit

    async def generate(self, plan: SessionPlan) -> GeneratedSet:
        contexts = await build_contexts(
            self._store, self._embedder, plan, top_k=self._top_k
        )
        previous = {
            concept.id: self._store.previous_question_texts(
                concept.id, self._previous_limit
            )
            for concept in _plan_concepts(plan)
        }
        repair_count = 0

        try:
            system, user = build_generation_messages(
                plan, contexts, previous_texts=previous
            )
            raw = await self._llm.grade(system, user)
            try:
                drafts = parse_generation(raw, plan)
            except GenerationError as exc:
                # 解析失败无法定位槽位，整场修复一次。
                drafts = ()
                result = ValidationResult(
                    ok=False,
                    errors=(str(exc),),
                    failed_slots=(1, 2, 3, 4, 5),
                )
            else:
                result = validate_question_set(
                    drafts, contexts, plan, previous_texts=previous
                )

            if not result.ok:
                repair_count = 1
                repaired = await self._repair(
                    plan, contexts, drafts, result, previous
                )
                drafts = apply_repair(
                    drafts,
                    repaired,
                    failed_slots=result.failed_slots,
                    contexts=contexts,
                    plan=plan,
                    previous_texts=previous,
                )
        except GenerationError:
            raise
        except Exception as exc:
            raise GenerationError(f"出题失败：{exc}") from exc

        questions = tuple(
            to_generated_question(
                draft, _require_chunk(contexts, draft.concept_id, draft.source_ref)
            )
            for draft in drafts
        )
        return GeneratedSet(
            questions=questions,
            meta={
                "origin": "generated",
                "model": self._model,
                "prompt_version": self._prompt_version,
                "retrieved_chunk_ids": [
                    chunk.chunk_id
                    for context in contexts.values()
                    for chunk in context.chunks
                    if chunk.origin == "retrieval"
                ],
                "repair_count": repair_count,
                "validation": "passed",
            },
        )

    async def _repair(
        self,
        plan: SessionPlan,
        contexts,
        drafts: Sequence[QuestionDraft],
        result: ValidationResult,
        previous,
    ) -> tuple[QuestionDraft, ...]:
        messages = build_repair_messages(
            plan,
            contexts,
            drafts,
            failed_slots=result.failed_slots,
            errors=result.errors,
            previous_texts=previous,
        )
        return parse_generation(
            await self._llm.grade(*messages), plan, slots=result.failed_slots
        )


def _require_chunk(contexts, concept_id: str, ref: int) -> ContextChunk:
    context = contexts.get(concept_id)
    if context is not None:
        for chunk in context.chunks:
            if chunk.ref == ref:
                return chunk
    raise GenerationError(f"槽位上下文缺失：{concept_id}#{ref}")
