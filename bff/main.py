"""BFF 入口：静态资源 + WebSocket 会话编排。

协议（与 web/app.js 对齐）：
  客户端 → 服务端
    {"type":"session_start","kind":"daily"}
    {"type":"session_resume","session_id":"..."}
    {"type":"answer","session_id":"...","question_id":1,"turn_id":"...","text":"...","input_mode":"voice"|"text","retry":false}
    {"type":"finish","session_id":"..."}
    {"type":"audio","session_id":"...","question_id":1,"turn_id":"...","data":"<base64>","sample_rate":16000,"mime":"audio/wav","retry":false}
    {"type":"ping"}
  服务端 → 客户端
    {"type":"ready","fake":bool,"modes":{...},"notes":[...]}
    {"type":"session_ready","session_id":"...","kind":"daily","intro":"...","focus":{"concept_id":"...","name":"...","reason_kind":"..."},"unit":{"kind":"daily","main":{...},"review":{...}|null},"question":{...}}
    {"type":"lecture","session_id":"...","text":"..."}
    {"type":"question","id":1,"role":"new","kind":"recall","text":"...","options":null,"index":1,"total":5}
    {"type":"transcript","turn_id":"...","text":"...","confidence":null,"needs_confirmation":false,"reason":null}
    {"type":"score","question_id":1,"score":70,"why":"...","turn_id":"..."}
    {"type":"probe","question_id":1,"text":"...","turn_id":"..."}
    {"type":"session_result","status":"completed","session_score":78.0,"mastery":{...},"review_due_at":"2026-11-24","concepts":[...],"scores":[...]}
    {"type":"session_expired","session_id":"..."}
    {"type":"audio_chunk","seq":1,"utterance":"filler|intro|lecture|question|feedback|teach","mime":"audio/wav","data":"<base64>"}
    {"type":"warning" | "error","stage":"...","message":"..."}

``retry=true`` 表示已评分题的重新作答：跳过重复判定，重新打分并覆盖同一行。
``audio_chunk`` 按句发送，同一 ``utterance`` 的 ``seq`` 递增。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from core.agent import Agent, Turn
from core.agent_loop import AgentLoop
from core.agent_steps import (
    build_clarify_brief,
    build_free_talk_brief,
    build_teach_brief,
    session_payload,
)
from core.agent_tools import (
    TOOL_READ_CONCEPT,
    TOOL_SEARCH_MATERIALS,
    TOOL_SEARCH_WEB,
)
from core.clock import SystemClock
from core.coach import Coach, NoSessionAvailable, SessionQuestion, Settlement, StartedSession
from core.concepts import load_concepts, sync_runtime
from core.db import connect, init_schema
from core.demo import load_demo
from core.emotion import MIDPOINT, tone_hint as emotion_tone_hint
from core.fixture import load_fixture
from core.free_talk import (
    MAX_HISTORY_MESSAGES,
    NO_MATERIAL_PREFIX,
    build_free_talk_messages,
    format_material_context,
    format_progress,
    format_web_context,
)
from core.ports import ASRRequest, AgentMessage, ChatMessage, JsonScorer, SearchHit
from core.persona import default_persona, load_persona, render_persona
from core.router import classify_free_talk, is_mixed, is_suspicious, needs_web, search_query
from core.store import SessionAlreadyFinalized, Store
from core.tts_cache import TTSCache
from core.tts_text import split_for_tts
from core.version import app_version

from .admin import router as admin_router
from .admin_task_runner import TaskRunner
from .agent_llm import FakeAgentClient, OpenAIAgentClient
from .agent_tools import build_agent_tools
from .config import MODE_FAKE, Settings, load_settings
from .emotion import EmotionUpdater
from .history import router as history_router
from .knowledge import router as knowledge_router
from .lecture import generate_lecture
from .memory import MemoryService
from .memory_extraction import MemoryExtractor
from .providers.base import ProviderError
from .providers.registry import Providers, build_providers
from .question_generation import BffQuestionGenerator
from .retrieval import is_grounded, retrieve_text
from .web_sources import filter_web_results, merge_sources, web_context_items

MAX_AUDIO_BYTES = 20 * 1024 * 1024
# base64 膨胀约 4/3；先按字符串长度挡掉超大包，避免解码后再发现。
MAX_AUDIO_B64_CHARS = MAX_AUDIO_BYTES * 4 // 3 + 16
TTS_RETRY_SECONDS = 1.0
TTS_UNAVAILABLE_MESSAGE = "语音暂时不可用，文字继续"
# 点击「开始今天的学习」后立刻播的短句，启动时预合成。
OPENING_FILLER = "好，让我看一下今天学什么。"

logger = logging.getLogger(__name__)


def _options(raw: Any) -> Any:
    if raw is None or not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _sources(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _question_origin(question: dict[str, Any]) -> str | None:
    raw = question.get("generation_meta_json")
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if isinstance(data, dict) and data.get("origin"):
        return str(data["origin"])
    return None


def _question_event(
    store: Store, session_id: str, question: dict[str, Any]
) -> dict[str, Any]:
    rows = store.session_questions(session_id)
    ids = [row["id"] for row in rows]
    index = ids.index(question["id"]) + 1 if question["id"] in ids else 1
    return {
        "type": "question",
        "id": question["id"],
        "role": question["question_role"],
        "kind": question["kind"],
        "question_type": question.get("question_type"),
        "origin": _question_origin(question),
        "text": question["question_text"],
        "options": _options(question.get("options_json")),
        "index": index,
        "total": len(rows),
    }


def _started_question_event(
    session_id: str, question: SessionQuestion
) -> dict[str, Any]:
    return {
        "type": "question",
        "session_id": session_id,
        "id": question.id,
        "role": question.role,
        "kind": question.kind,
        "question_type": question.question_type,
        "origin": question.origin,
        "text": question.text,
        "options": question.options,
        "index": question.index,
        "total": question.total,
    }


def _concept_name(concepts: list[Any], concept_id: str) -> str:
    for concept in concepts:
        if concept.id == concept_id:
            return concept.name
    return concept_id


def _unit_event(
    store: Store, concepts: list[Any], session_id: str
) -> dict[str, Any]:
    """从本场题目推导主/复习概念；概念名缺失时回退 id。"""
    main_id: str | None = None
    review_id: str | None = None
    for question in store.session_questions(session_id):
        concept_id = question.get("concept_id")
        if not concept_id:
            continue
        key = str(concept_id)
        if question.get("question_role") == "new" and main_id is None:
            main_id = key
        elif question.get("question_role") == "review" and review_id is None:
            review_id = key

    agent = store.agent_session(session_id)
    kind = str(agent["kind"]) if agent is not None else "daily"

    def card(concept_id: str | None) -> dict[str, str] | None:
        if concept_id is None:
            return None
        return {"id": concept_id, "name": _concept_name(concepts, concept_id)}

    return {"kind": kind, "main": card(main_id), "review": card(review_id)}


def _result_event(settlement: Settlement, *, turn_id: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "session_result",
        "session_id": settlement.session_id,
        "status": settlement.status,
        "session_score": settlement.session_score,
        "mastery": settlement.mastery,
        "review_due_at": settlement.review_due_at,
        "concepts": [
            {
                "id": concept.concept_id,
                "name": concept.name,
                "roles": list(concept.roles),
                "new_score": concept.new_score,
                "review_score": concept.review_score,
                "mastery_before": concept.mastery_before,
                "mastery_before_label": concept.mastery_before_label,
                "mastery_after": concept.mastery_after,
                "mastery_after_label": concept.mastery_after_label,
                "mastery_updated": concept.mastery_updated,
                "review_due_at": concept.review_due_at,
            }
            for concept in settlement.concepts
        ],
        "scores": [
            {
                "question_id": answer.question_id,
                "score": answer.score,
                "why": answer.why,
                "question_type": answer.question_type,
                "source_url": answer.source_url,
                "source_excerpt": answer.source_excerpt,
            }
            for answer in settlement.scores
        ],
    }
    if turn_id is not None:
        event["turn_id"] = turn_id
    return event


async def _synthesize_locked(
    cache: TTSCache, text: str, lock: asyncio.Lock
) -> tuple[bytes, str]:
    """TTS 全局串行；失败等一秒重试一次（含 429 并发上限）。"""
    async with lock:
        try:
            return await cache.get_or_synthesize(text)
        except ProviderError:
            await asyncio.sleep(TTS_RETRY_SECONDS)
            return await cache.get_or_synthesize(text)


async def _send_utterance_audio(
    sock: WebSocket,
    cache: TTSCache,
    text: str,
    lock: asyncio.Lock,
    *,
    utterance: str,
) -> None:
    """逐句合成并按序发送：第一句合成完就能播，不必等整段。"""
    for seq, segment in enumerate(split_for_tts(text), start=1):
        try:
            audio, mime = await _synthesize_locked(cache, segment, lock)
        except ProviderError as exc:
            logger.warning("TTS synthesize failed: %s", exc)
            await sock.send_json(
                {
                    "type": "warning",
                    "stage": "tts",
                    "message": TTS_UNAVAILABLE_MESSAGE,
                }
            )
            return
        if not audio:
            continue
        await sock.send_json(
            {
                "type": "audio_chunk",
                "seq": seq,
                "utterance": utterance,
                "mime": mime,
                "data": base64.b64encode(audio).decode("ascii"),
            }
        )


async def _send_question_audio(
    sock: WebSocket, cache: TTSCache, text: str, lock: asyncio.Lock
) -> None:
    await _send_utterance_audio(sock, cache, text, lock, utterance="question")


async def _send_intro_audio(
    sock: WebSocket, cache: TTSCache, text: str, lock: asyncio.Lock
) -> None:
    await _send_utterance_audio(sock, cache, text, lock, utterance="intro")


async def _prewarm(cache: TTSCache, texts: list[str], lock: asyncio.Lock) -> None:
    for text in texts:
        for segment in split_for_tts(text):
            try:
                await _synthesize_locked(cache, segment, lock)
            except Exception:
                continue


async def _stream_feedback(
    sock: WebSocket,
    providers: Providers,
    cache: TTSCache,
    text: str,
    lock: asyncio.Lock,
    *,
    utterance: str = "feedback",
) -> None:
    if not text.strip():
        return

    stream = getattr(providers.tts, "stream", None)
    if callable(stream):
        mime = str(getattr(providers.tts, "stream_mime", "audio/mpeg"))
        for attempt in (1, 2):
            seq = 0
            try:
                async with lock:
                    async for chunk in stream(text):
                        if not chunk:
                            continue
                        seq += 1
                        await sock.send_json(
                            {
                                "type": "audio_chunk",
                                "seq": seq,
                                "utterance": utterance,
                                "mime": mime,
                                "data": base64.b64encode(chunk).decode("ascii"),
                            }
                        )
            except ProviderError as exc:
                if seq == 0 and attempt == 1:
                    await asyncio.sleep(TTS_RETRY_SECONDS)
                    continue
                logger.warning("TTS stream failed: %s", exc)
                await sock.send_json(
                    {
                        "type": "warning",
                        "stage": "tts",
                        "message": TTS_UNAVAILABLE_MESSAGE,
                    }
                )
                return
            if seq:
                return
            break

    # 不支持流式的 provider（如 DeepSeek）：逐句合成，先播第一句。
    await _send_utterance_audio(sock, cache, text, lock, utterance=utterance)


async def _send_turn(
    sock: WebSocket,
    store: Store,
    turn: Turn,
    *,
    session_id: str,
    turn_id: str | None,
    providers: Providers,
    cache: TTSCache,
    lock: asyncio.Lock,
    on_settled: Callable[[Settlement], None] | None = None,
) -> None:
    if turn.answer is not None:
        await sock.send_json(
            {
                "type": "score",
                "question_id": turn.answer.question_id,
                "score": turn.answer.score,
                "why": turn.answer.why,
                "question_type": turn.answer.question_type,
                "source_url": turn.answer.source_url,
                "source_excerpt": turn.answer.source_excerpt,
                "duplicate": turn.duplicate,
                "turn_id": turn_id,
            }
        )
    if turn.kind == "probe":
        await sock.send_json(
            {
                "type": "probe",
                "question_id": turn.next_question["id"] if turn.next_question else None,
                "text": turn.probe,
                "turn_id": turn_id,
            }
        )
        return

    # 先告诉客户端下一题/结果，反馈语音随后再流式补上；
    # 用户点「下一题」时可以立刻切走，不必等语音生成完。
    if turn.settlement is not None:
        await sock.send_json(_result_event(turn.settlement, turn_id=turn_id))
        if on_settled is not None:
            on_settled(turn.settlement)
    if turn.next_question is not None:
        await sock.send_json(_question_event(store, session_id, turn.next_question))

    if turn.answer is not None:
        if turn.answer.speak:
            await _stream_feedback(sock, providers, cache, turn.answer.why, lock)
        await sock.send_json({"type": "feedback_end", "turn_id": turn_id})

    if turn.next_question is not None:
        await _send_question_audio(
            sock, cache, str(turn.next_question["question_text"]), lock
        )


def _emotion_payload(updater: EmotionUpdater | None) -> dict[str, object]:
    """关闭情绪时返回中间态，前端保持 neutral。"""
    if updater is None:
        return {
            "comfort": MIDPOINT.comfort,
            "energy": MIDPOINT.energy,
            "tone": emotion_tone_hint(MIDPOINT),
        }
    return updater.event_payload()


async def _opening_lecture(
    scorer: JsonScorer,
    store: Store,
    concepts: list[Any],
    started: StartedSession,
) -> str:
    """开场只介绍今天这个概念；拿不到概念就不讲。"""
    concept_id = started.focus.concept_id if started.focus is not None else None
    if concept_id is None:
        row = store.question(started.questions[0].id)
        concept_id = row.get("concept_id") if row else None
    concept = _concept_by_id(concepts, concept_id)
    if concept is None:
        return ""
    return await generate_lecture(scorer, concept)


async def _send_session_ready(
    sock: WebSocket,
    started: StartedSession,
    cache: TTSCache,
    background: set[asyncio.Task],
    lock: asyncio.Lock,
    *,
    unit: dict[str, Any],
    opening_line: str | None = None,
    lecture_task: asyncio.Task[str] | None = None,
    emotion: dict[str, object] | None = None,
) -> None:
    intro = (opening_line or "").strip()
    if intro and intro[-1] not in "。！？…":
        intro += "。"
    first = started.questions[0]
    event: dict[str, Any] = {
        "type": "session_ready",
        "session_id": started.session_id,
        "kind": started.kind,
        "intro": intro,
        "unit": unit,
        "question": _started_question_event(started.session_id, first),
        "emotion": emotion or _emotion_payload(None),
    }
    if started.focus is not None:
        event["focus"] = {
            "concept_id": started.focus.concept_id,
            "name": started.focus.name,
            "reason_kind": started.focus.reason_kind,
        }
    await sock.send_json(event)
    if intro:
        await _send_intro_audio(sock, cache, intro, lock)

    # 生活句先出声，讲解在这段时间里生成；生成完再讲、再读第一题。
    if lecture_task is not None:
        lecture = await lecture_task
        if lecture.strip():
            await sock.send_json(
                {
                    "type": "lecture",
                    "session_id": started.session_id,
                    "text": lecture,
                }
            )
            await _send_utterance_audio(sock, cache, lecture, lock, utterance="lecture")

    await _send_question_audio(sock, cache, first.text, lock)

    rest = [question.text for question in started.questions[1:]]
    if rest:
        task = asyncio.create_task(_prewarm(cache, rest, lock))
        background.add(task)
        task.add_done_callback(background.discard)


def _schedule_memory(app: FastAPI, settlement: Settlement) -> None:
    """结算后异步提炼；不阻塞 session_result，闭页面也继续跑。"""
    extractor: MemoryExtractor | None = app.state.memory_extractor
    if extractor is None or settlement.status not in ("completed", "partial"):
        return
    task = asyncio.create_task(extractor.run(settlement.session_id))
    app.state.memory_tasks.add(task)
    task.add_done_callback(app.state.memory_tasks.discard)


def _build_agent_client(config: Settings):
    """默认 DeepSeek；fake 模式或未配置时退回固定回复。"""
    if config.agent_base_url and config.mode != MODE_FAKE:
        return OpenAIAgentClient(
            base_url=config.agent_base_url,
            api_key=config.agent_api_key,
            model=config.agent_model or "deepseek-chat",
            timeout=15.0,
            max_retries=1,
        )
    return FakeAgentClient()


def _resolve_content_dir(content_dir: Path, project_root: Path) -> Path | None:
    """找一份带概念与题库的内容目录。

    显式 `CONTENT_DIR` 只认它自己（缺内容就退 fixture）；默认目录才追加 `demo/` 回退。
    """
    if content_dir != project_root:
        candidates = [content_dir]
    else:
        candidates = [project_root, project_root / "demo"]
    for base in candidates:
        if (base / "concepts.yaml").is_file() and (
            base / "seeds" / "question_bank.json"
        ).is_file():
            return base
    return None


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or load_settings()
    fixture_dir = config.project_root / "seeds" / "fixture"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = config
        providers: Providers = build_providers(config)
        app.state.providers = providers

        conn = connect(config.db_path)
        init_schema(conn)
        store = Store(conn)
        content_dir = _resolve_content_dir(config.content_dir, config.project_root)
        demo_dir = config.project_root / "demo"
        if content_dir is not None and content_dir.resolve() == demo_dir.resolve():
            concepts = load_demo(store, demo_dir)
        elif content_dir is not None:
            concepts = load_concepts(content_dir / "concepts.yaml")
            sync_runtime(store, concepts)
            store.import_question_bank(
                json.loads(
                    (content_dir / "seeds" / "question_bank.json").read_text(
                        encoding="utf-8"
                    )
                )
            )
        else:
            load_fixture(
                store,
                fixture_dir / "fixture-concepts.yaml",
                fixture_dir / "fixture-question-bank.json",
            )
            concepts = load_concepts(fixture_dir / "fixture-concepts.yaml")
        persona_path = config.content_dir / "persona.yaml"
        app.state.persona = (
            load_persona(persona_path)
            if persona_path.is_file()
            else default_persona()
        )
        app.state.persona_block = render_persona(app.state.persona)
        clock = SystemClock()
        coach = Coach(
            store,
            concepts,
            clock=clock,
            scorer=providers.scorer,
            generator=BffQuestionGenerator(
                store,
                providers.embedder,
                providers.scorer,
                model=config.scorer.model or "deepseek-chat",
            ),
        )
        app.state.store = store
        app.state.emotion = (
            EmotionUpdater(
                store,
                providers.scorer,
                user_id=config.user_id,
                user_role=config.user_role,
            )
            if config.emotion_enabled
            else None
        )
        app.state.memory = (
            MemoryService(store, user_id=config.user_id)
            if config.memory_enabled
            else None
        )
        app.state.memory_extractor = (
            MemoryExtractor(
                store,
                providers.scorer,
                user_id=config.user_id,
            )
            if config.memory_enabled
            else None
        )
        memory_tasks: set[asyncio.Task] = set()
        app.state.memory_tasks = memory_tasks
        app.state.clock = clock
        app.state.concepts = concepts
        app.state.coach = coach
        app.state.agent = Agent(store, coach, clock=clock, llm=providers.llm)
        agent_client = None
        agent_loop = None
        if config.agent_harness:
            agent_client = _build_agent_client(config)
            agent_loop = AgentLoop(
                agent_client,
                build_agent_tools(
                    store=store,
                    embedder=providers.embedder,
                    search=providers.search,
                    concepts=concepts,
                    min_cosine=config.retrieval_min_cosine,
                    search_timeout_seconds=config.search_timeout_seconds,
                    today=clock.today,
                ),
                persona=app.state.persona,
            )
        app.state.agent_loop = agent_loop
        app.state.agent_client = agent_client
        app.state.tts_cache = TTSCache(
            providers.tts,
            config.data_dir / "audio_cache",
            voice=config.tts_voice,
            model=f"{providers.tts.name}:{config.tts.model or config.tts_kind}",
            output_format=config.tts_output_format,
        )
        app.state.tts_lock = asyncio.Lock()
        background: set[asyncio.Task] = set()
        app.state.background = background
        # 开场短句在启动时预合成，点「开始今天的学习」时命中缓存即可出声。
        warm = asyncio.create_task(
            _prewarm(app.state.tts_cache, [OPENING_FILLER], app.state.tts_lock)
        )
        background.add(warm)
        warm.add_done_callback(background.discard)
        task_runner = None
        if config.admin_task_runner:
            task_runner = TaskRunner(store, config)
            await task_runner.start()
        app.state.task_runner = task_runner
        try:
            yield
        finally:
            if task_runner is not None:
                await task_runner.stop()
            for task in background:
                task.cancel()
            if background:
                await asyncio.gather(*background, return_exceptions=True)
            for task in memory_tasks:
                task.cancel()
            if memory_tasks:
                await asyncio.gather(*memory_tasks, return_exceptions=True)
            if agent_client is not None:
                close = getattr(agent_client, "aclose", None)
                if close is not None:
                    await close()
            store.close()
            await providers.aclose()

    app = FastAPI(title="MOMO 学习搭子", lifespan=lifespan)
    app.include_router(knowledge_router)
    app.include_router(admin_router)
    app.include_router(history_router)

    @app.get("/health")
    async def health() -> dict[str, object]:
        providers: Providers = app.state.providers
        return {
            "ok": True,
            "version": app_version(),
            "fake": providers.any_fake,
            "modes": providers.modes,
            "notes": providers.notes,
            "providers": config.summary(),
        }

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/", include_in_schema=False)
    async def admin_index() -> Any:
        index = config.web_dir / "admin" / "index.html"
        if not index.is_file():
            return HTMLResponse(
                "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
                "<title>管理后台未构建</title>"
                "<body style=\"font-family:system-ui;padding:32px;line-height:1.7\">"
                "<h1>管理后台未构建</h1>"
                "<p>请在项目根目录运行：</p>"
                "<pre>cd admin-ui\nnpm ci\nnpm run build</pre>"
                "<p>然后刷新本页。</p></body></html>",
                status_code=503,
            )
        return FileResponse(index)

    @app.websocket("/ws")
    async def websocket_endpoint(sock: WebSocket) -> None:
        providers: Providers = app.state.providers
        store: Store = app.state.store
        agent: Agent = app.state.agent
        cache: TTSCache = app.state.tts_cache
        lock: asyncio.Lock = app.state.tts_lock
        background: set[asyncio.Task] = app.state.background
        clock: SystemClock = app.state.clock
        concepts = app.state.concepts
        persona = app.state.persona
        life_pool = persona.life_pool
        persona_block = app.state.persona_block
        agent_loop: AgentLoop | None = app.state.agent_loop
        emotion: EmotionUpdater | None = app.state.emotion
        memory: MemoryService | None = app.state.memory
        on_settled = lambda settlement: _schedule_memory(app, settlement)
        teach_state: dict[str, Any] = {"question_id": None, "messages": []}
        await sock.accept()
        await sock.send_json(
            {
                "type": "ready",
                "fake": providers.any_fake,
                "modes": providers.modes,
                "notes": providers.notes,
                "agent_harness": agent_loop is not None,
                "emotion": _emotion_payload(emotion),
            }
        )

        try:
            while True:
                message = await sock.receive_json()
                if not isinstance(message, dict):
                    await _error(sock, "protocol", "消息必须是 JSON 对象")
                    continue

                kind = message.get("type")
                if kind == "ping":
                    await sock.send_json({"type": "pong"})
                    continue

                if kind == "conversation_list":
                    await _send_conversation_list(sock, store)
                    continue

                if kind == "conversation_new":
                    await _handle_conversation_new(sock, store, clock)
                    continue

                if kind == "conversation_load":
                    await _handle_conversation_load(sock, store, message)
                    continue

                if kind == "conversation_rename":
                    await _handle_conversation_rename(sock, store, message)
                    continue

                if kind == "conversation_delete":
                    await _handle_conversation_delete(sock, store, message)
                    continue

                if kind == "session_start":
                    teach_state["question_id"] = None
                    teach_state["messages"] = []
                    filler = asyncio.create_task(
                        _send_utterance_audio(
                            sock, cache, OPENING_FILLER, lock, utterance="filler"
                        )
                    )
                    try:
                        started = await agent.start()
                    except NoSessionAvailable as exc:
                        await filler
                        await _error(sock, "session", str(exc))
                        continue
                    await filler
                    await _send_session_ready(
                        sock,
                        started,
                        cache,
                        background,
                        lock,
                        unit=_unit_event(store, concepts, started.session_id),
                        opening_line=life_pool.for_date(clock.today()),
                        lecture_task=asyncio.create_task(
                            _opening_lecture(providers.scorer, store, concepts, started)
                        ),
                        emotion=_emotion_payload(emotion),
                    )
                    continue

                if kind == "session_resume":
                    teach_state["question_id"] = None
                    teach_state["messages"] = []
                    session_id = str(message.get("session_id") or "")
                    resumed = agent.resume(session_id)
                    if resumed.expired:
                        await sock.send_json(
                            {"type": "session_expired", "session_id": session_id}
                        )
                        continue
                    if resumed.settlement is not None:
                        await sock.send_json(_result_event(resumed.settlement))
                        _schedule_memory(app, resumed.settlement)
                        continue
                    if resumed.question is not None and resumed.session_id is not None:
                        await sock.send_json(
                            {
                                "type": "session_ready",
                                "session_id": resumed.session_id,
                                "kind": store.agent_session(resumed.session_id)["kind"],  # type: ignore[index]
                                "unit": _unit_event(store, concepts, resumed.session_id),
                                "question": _question_event(
                                    store, resumed.session_id, resumed.question
                                ),
                                "emotion": _emotion_payload(emotion),
                            }
                        )
                        await _send_question_audio(
                            sock, cache, str(resumed.question["question_text"]), lock
                        )
                    continue

                if kind == "repeat":
                    await _handle_repeat(
                        sock, agent, store, clock, cache, lock, message
                    )
                    continue

                if kind == "answer":
                    await _handle_answer(
                        sock,
                        agent,
                        store,
                        message,
                        providers,
                        cache,
                        lock,
                        on_settled=on_settled,
                    )
                    continue

                if kind == "skip":
                    session_id = str(message.get("session_id") or "")
                    question_id = message.get("question_id")
                    if not session_id or not isinstance(question_id, int):
                        await _error(sock, "protocol", "skip 需要 session_id 与 question_id")
                        continue
                    try:
                        turn = agent.skip(session_id, question_id)
                    except (KeyError, ValueError, SessionAlreadyFinalized) as exc:
                        await _error(sock, "session", str(exc))
                        continue
                    teach_state["question_id"] = None
                    teach_state["messages"] = []
                    await _send_turn(
                        sock,
                        store,
                        turn,
                        session_id=session_id,
                        turn_id=message.get("turn_id"),
                        providers=providers,
                        cache=cache,
                        lock=lock,
                        on_settled=on_settled,
                    )
                    continue

                if kind == "reveal":
                    await _handle_reveal(sock, store, clock, message)
                    continue

                if kind == "finish":
                    session_id = str(message.get("session_id") or "")
                    try:
                        settlement = agent.finish(session_id)
                    except SessionAlreadyFinalized as exc:
                        await sock.send_json(
                            {
                                "type": "error",
                                "stage": "session",
                                "code": "session_finished",
                                "message": str(exc),
                            }
                        )
                        continue
                    except (KeyError, ValueError) as exc:
                        await _error(sock, "session", str(exc))
                        continue
                    teach_state["question_id"] = None
                    teach_state["messages"] = []
                    await sock.send_json(
                        _result_event(settlement, turn_id=message.get("turn_id"))
                    )
                    _schedule_memory(app, settlement)
                    continue

                if kind == "text":
                    has_session = bool(message.get("session_id")) and isinstance(
                        message.get("question_id"), int
                    )
                    intent = str(message.get("intent") or "")
                    if has_session and intent in ("teach", "clarify"):
                        if agent_loop:
                            await _handle_teach(
                                sock,
                                agent,
                                agent_loop,
                                store,
                                concepts,
                                clock,
                                message,
                                providers,
                                cache,
                                lock,
                                teach_state,
                                emotion,
                            )
                        else:
                            await _error(sock, "agent", "教学/澄清未启用")
                    elif has_session and _is_repeat_command(message.get("text")):
                        await _handle_repeat(
                            sock, agent, store, clock, cache, lock, message
                        )
                    elif has_session:
                        await _handle_answer(
                            sock,
                            agent,
                            store,
                            message,
                            providers,
                            cache,
                            lock,
                            on_settled=on_settled,
                        )
                    else:
                        await _handle_free_talk_text(
                            sock,
                            providers,
                            config,
                            message,
                            lock,
                            store,
                            clock,
                            concepts,
                            cache,
                            agent_loop=agent_loop,
                            persona_block=persona_block,
                            emotion=emotion,
                            memory=memory,
                        )
                    continue

                if kind == "audio":
                    session_id = str(message.get("session_id") or "")
                    question_id = message.get("question_id")
                    if not session_id or not isinstance(question_id, int):
                        await _handle_free_talk(
                            sock,
                            providers,
                            config,
                            message,
                            lock,
                            store,
                            clock,
                            concepts,
                            cache,
                            agent_loop=agent_loop,
                            persona_block=persona_block,
                            emotion=emotion,
                            memory=memory,
                        )
                    else:
                        await _handle_audio(
                            sock,
                            providers,
                            config,
                            agent,
                            store,
                            message,
                            cache,
                            lock,
                            on_settled=on_settled,
                        )
                    continue

                await _error(sock, "protocol", f"不认识的消息类型：{kind}")
        except WebSocketDisconnect:
            return
        except Exception as exc:  # pragma: no cover - 保持连接可诊断
            try:
                await sock.send_json({"type": "error", "stage": "server", "message": str(exc)})
            except Exception:
                pass

    if config.assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(config.assets_dir)), name="assets")
    app.mount("/", StaticFiles(directory=str(config.web_dir), html=True), name="web")
    return app


def _audio_bytes(message: dict[str, Any]) -> tuple[bytes, int]:
    data = message.get("data")
    if not isinstance(data, str) or not data:
        raise ValueError("音频为空")
    if len(data) > MAX_AUDIO_B64_CHARS:
        raise ValueError("录音太长，请控制在 20MB 以内")
    try:
        return base64.b64decode(data, validate=True), int(message.get("sample_rate") or 16000)
    except (binascii.Error, ValueError, TypeError):
        raise ValueError("音频格式不对") from None


def _progress_summary(store: Store, concepts: list[Any]) -> str:
    states = {state.id: state for state in store.concept_states()}
    active = [
        (concept.name, states[concept.id].mastery, states[concept.id].review_due_at)
        for concept in concepts
        if concept.id in states and states[concept.id].status == "active"
    ]
    active.sort(key=lambda item: (item[1], item[0]))
    sessions = [
        (row["date"], row["kind"], row["status"], row["session_score"])
        for row in store.recent_sessions(3)
    ]
    return format_progress(active, sessions)


def _resolve_conversation(store: Store, requested: str, now: str) -> str:
    if requested:
        if store.conversation(requested) is None:
            store.create_conversation(conversation_id=requested, created_at=now)
        return requested
    latest = store.latest_conversation()
    if latest is not None:
        return str(latest["id"])
    conversation_id = uuid.uuid4().hex
    store.create_conversation(conversation_id=conversation_id, created_at=now)
    return conversation_id


async def _send_conversation_list(sock: WebSocket, store: Store) -> None:
    items = [
        {
            "conversation_id": row["id"],
            "title": row["title"],
            "updated_at": row["updated_at"],
            "message_count": row["message_count"],
        }
        for row in store.conversations(limit=50)
    ]
    await sock.send_json({"type": "conversation_list", "items": items})


async def _handle_conversation_new(
    sock: WebSocket, store: Store, clock: SystemClock
) -> None:
    conversation_id = uuid.uuid4().hex
    now = clock.now()
    store.create_conversation(conversation_id=conversation_id, created_at=now)
    await sock.send_json(
        {
            "type": "conversation_created",
            "conversation_id": conversation_id,
            "title": None,
            "created_at": now,
        }
    )


async def _handle_conversation_load(
    sock: WebSocket, store: Store, message: dict[str, Any]
) -> None:
    conversation_id = str(message.get("conversation_id") or "")
    conversation = store.conversation(conversation_id)
    if conversation is None:
        await _error(sock, "conversation", "对话不存在")
        return
    messages = store.conversation_messages(conversation_id, limit=200)
    await sock.send_json(
        {
            "type": "conversation_loaded",
            "conversation_id": conversation_id,
            "title": conversation["title"],
            "messages": [
                {
                    "role": row["role"],
                    "text": row["text"],
                    "mode": row["mode"],
                    "sources": _sources(row.get("sources_json")),
                    "created_at": row["created_at"],
                }
                for row in messages
            ],
        }
    )


async def _handle_conversation_rename(
    sock: WebSocket, store: Store, message: dict[str, Any]
) -> None:
    conversation_id = str(message.get("conversation_id") or "")
    title = str(message.get("title") or "").strip()[:40]
    if not conversation_id or not title:
        await _error(sock, "protocol", "conversation_rename 需要 conversation_id 与非空 title")
        return
    if store.conversation(conversation_id) is None:
        await _error(sock, "conversation", "对话不存在")
        return
    store.rename_conversation(conversation_id, title)
    await sock.send_json(
        {
            "type": "conversation_renamed",
            "conversation_id": conversation_id,
            "title": title,
        }
    )


async def _handle_conversation_delete(
    sock: WebSocket, store: Store, message: dict[str, Any]
) -> None:
    conversation_id = str(message.get("conversation_id") or "")
    if not conversation_id:
        await _error(sock, "protocol", "conversation_delete 需要 conversation_id")
        return
    if store.conversation(conversation_id) is None:
        await _error(sock, "conversation", "对话不存在")
        return
    store.delete_conversation(conversation_id)
    await sock.send_json(
        {"type": "conversation_deleted", "conversation_id": conversation_id}
    )


async def _handle_free_talk(
    sock: WebSocket,
    providers: Providers,
    config: Settings,
    message: dict[str, Any],
    lock: asyncio.Lock,
    store: Store,
    clock: SystemClock,
    concepts: list[Any],
    cache: TTSCache,
    *,
    agent_loop: AgentLoop | None = None,
    persona_block: str = "",
    emotion: EmotionUpdater | None = None,
    memory: MemoryService | None = None,
) -> None:
    turn_id = str(message.get("turn_id") or "")
    try:
        raw, sample_rate = _audio_bytes(message)
    except ValueError as exc:
        await _error(sock, "asr", str(exc))
        return

    try:
        result = await providers.asr.transcribe(
            ASRRequest(
                audio=raw,
                mime=str(message.get("mime") or "audio/wav"),
                sample_rate=sample_rate,
                language=config.asr_language,
            )
        )
    except ProviderError as exc:
        await _error(sock, "asr", str(exc))
        return

    text = result.text.strip()
    if not text:
        await _error(sock, "asr", "没听清，再说一次？")
        return

    conversation_id = _resolve_conversation(
        store, str(message.get("conversation_id") or ""), clock.now()
    )
    await sock.send_json(
        {
            "type": "transcript",
            "turn_id": turn_id,
            "conversation_id": conversation_id,
            "text": text,
            "confidence": result.confidence,
            "needs_confirmation": False,
            "reason": None,
        }
    )
    await _free_talk_reply(
        sock,
        providers,
        config,
        text,
        turn_id=turn_id,
        conversation_id=conversation_id,
        store=store,
        clock=clock,
        concepts=concepts,
        lock=lock,
        cache=cache,
        mode=str(message.get("mode") or ""),
        agent_loop=agent_loop,
        persona_block=persona_block,
        emotion=emotion,
        memory=memory,
    )


async def _handle_free_talk_text(
    sock: WebSocket,
    providers: Providers,
    config: Settings,
    message: dict[str, Any],
    lock: asyncio.Lock,
    store: Store,
    clock: SystemClock,
    concepts: list[Any],
    cache: TTSCache,
    *,
    agent_loop: AgentLoop | None = None,
    persona_block: str = "",
    emotion: EmotionUpdater | None = None,
    memory: MemoryService | None = None,
) -> None:
    text = str(message.get("text") or "").strip()
    if not text:
        await _error(sock, "llm", "说点什么吧")
        return
    turn_id = str(message.get("turn_id") or "")
    conversation_id = _resolve_conversation(
        store, str(message.get("conversation_id") or ""), clock.now()
    )
    await sock.send_json(
        {
            "type": "transcript",
            "turn_id": turn_id,
            "conversation_id": conversation_id,
            "text": text,
            "confidence": None,
            "needs_confirmation": False,
            "reason": None,
        }
    )
    await _free_talk_reply(
        sock,
        providers,
        config,
        text,
        turn_id=turn_id,
        conversation_id=conversation_id,
        store=store,
        clock=clock,
        concepts=concepts,
        lock=lock,
        cache=cache,
        mode=str(message.get("mode") or ""),
        agent_loop=agent_loop,
        persona_block=persona_block,
        emotion=emotion,
        memory=memory,
    )


async def _free_talk_reply(
    sock: WebSocket,
    providers: Providers,
    config: Settings,
    text: str,
    *,
    turn_id: str,
    conversation_id: str,
    store: Store,
    clock: SystemClock,
    concepts: list[Any],
    lock: asyncio.Lock,
    cache: TTSCache,
    mode: str = "",
    agent_loop: AgentLoop | None = None,
    persona_block: str = "",
    emotion: EmotionUpdater | None = None,
    memory: MemoryService | None = None,
) -> None:
    memory_context = ""
    if memory is not None:
        try:
            recalled = memory.recall(text)
        except Exception:
            logger.warning("memory_recall_failed", exc_info=True)
            recalled = None
        if recalled is not None:
            memory_context = recalled or "（没有找到相关记忆）"

    tone_hint = ""
    if emotion is not None:
        recent = [
            (row["role"], row["text"])
            for row in store.recent_conversation_messages(conversation_id, 6)
        ]
        state = await emotion.update(text, recent)
        tone_hint = emotion_tone_hint(state)
        await sock.send_json(
            {
                "type": "emotion",
                "comfort": round(state.comfort, 3),
                "energy": round(state.energy, 3),
                "tone": tone_hint,
            }
        )

    if agent_loop is not None:
        await _agent_free_talk_reply(
            sock,
            providers,
            config,
            text,
            turn_id=turn_id,
            conversation_id=conversation_id,
            store=store,
            clock=clock,
            concepts=concepts,
            lock=lock,
            cache=cache,
            agent_loop=agent_loop,
            tone_hint=tone_hint,
            memory_context=memory_context,
        )
        return
    if mode not in ("chat", "teach"):
        mode = classify_free_talk(text)
    hits: list[Any] = []
    try:
        hits = await retrieve_text(store, providers.embedder, text, top_k=3)
    except Exception:
        hits = []
    grounded = is_grounded(hits, min_cosine=config.retrieval_min_cosine)
    used = hits if grounded else []

    wants_web = needs_web(text) or not grounded
    web_hits: list[SearchHit] = []
    web_status = "off"
    if wants_web:
        search = providers.search
        if getattr(search, "name", "") == "search-off":
            web_status = "off"
        else:
            query = search_query(text, today=clock.today())
            if not query:
                web_status = "empty"
            else:
                try:
                    raw = await asyncio.wait_for(
                        search.search(query, max_results=config.search_max_results),
                        timeout=config.search_timeout_seconds,
                    )
                    web_hits = filter_web_results(query, raw)
                    web_status = "ok" if web_hits else "empty"
                except asyncio.TimeoutError:
                    web_status = "failed"
                    await sock.send_json(
                        {"type": "warning", "stage": "search", "message": "联网搜索超时"}
                    )
                except Exception as exc:
                    web_status = "failed"
                    await sock.send_json(
                        {"type": "warning", "stage": "search", "message": str(exc)}
                    )

    material_context = format_material_context(
        [
            {"index": index, "text": hit.text, "excerpt": hit.source_excerpt}
            for index, hit in enumerate(used, start=1)
        ]
    )
    retrieved_at = clock.today()
    web_items = web_context_items(
        web_hits, start_index=len(used) + 1, retrieved_at=retrieved_at
    )
    web_context = format_web_context(web_items)

    history = [
        ChatMessage(role=row["role"], content=row["text"])
        for row in store.recent_conversation_messages(
            conversation_id, MAX_HISTORY_MESSAGES
        )
    ]
    progress = _progress_summary(store, concepts)
    chat = providers.chat or providers.llm
    try:
        reply = (
            await chat.complete(
                build_free_talk_messages(
                    history,
                    text,
                    mode,
                    progress,
                    material_context,
                    web_context,
                    grounded=grounded,
                    web_status=web_status,
                    persona_block=persona_block,
                    tone_hint=tone_hint,
                    memory_context=memory_context,
                ),
                max_tokens=240,
            )
        ).strip()
    except ProviderError as exc:
        await _error(sock, "llm", str(exc))
        return
    if not reply:
        await _error(sock, "llm", "模型没有返回内容")
        return

    if not grounded and not web_hits:
        if web_status == "failed":
            prefix = "材料里没有直接讲到，联网搜索暂时不可用。"
        elif web_status == "empty":
            prefix = "材料里没有直接讲到，联网也没查到。"
        else:
            prefix = NO_MATERIAL_PREFIX
        if prefix not in reply:
            reply = f"{prefix}\n{reply}"

    sources = merge_sources(used, web_hits, retrieved_at=retrieved_at)
    store.append_conversation_message(
        conversation_id=conversation_id,
        role="user",
        text=text,
        created_at=clock.now(),
    )
    store.append_conversation_message(
        conversation_id=conversation_id,
        role="assistant",
        text=reply,
        mode=mode,
        sources=sources or None,
        created_at=clock.now(),
    )
    await sock.send_json(
        {
            "type": "reply",
            "conversation_id": conversation_id,
            "text": reply,
            "mode": mode,
            "sources": sources,
            "grounded": grounded,
            "web_status": web_status,
            "turn_id": turn_id,
        }
    )
    await _stream_feedback(sock, providers, cache, reply, lock)


def _progress_payload(store: Store, concepts: list[Any]) -> dict[str, Any]:
    states = {state.id: state for state in store.concept_states()}
    active = [
        {
            "id": concept.id,
            "name": concept.name,
            "mastery": states[concept.id].mastery,
            "review_due_at": states[concept.id].review_due_at,
        }
        for concept in concepts
        if concept.id in states and states[concept.id].status == "active"
    ]
    active.sort(key=lambda item: (item["mastery"], item["name"]))
    recent = [
        {
            "date": row["date"],
            "kind": row["kind"],
            "status": row["status"],
            "score": row["session_score"],
        }
        for row in store.recent_sessions(3)
    ]
    return {"active": active[:5], "recent": recent}


def _concept_by_id(concepts: list[Any], concept_id: Any):
    key = str(concept_id or "")
    return next((concept for concept in concepts if concept.id == key), None)


def _agent_web_status(results) -> str:
    status = "off"
    for result in results:
        if result.tool != TOOL_SEARCH_WEB:
            continue
        if result.ok:
            status = str((result.data or {}).get("status") or "ok")
        elif result.error is not None and result.error.code == "not_configured":
            status = "off"
        else:
            status = "failed"
    return status


async def _send_agent_status(
    sock: WebSocket, phase: str, tool: str | None, turn_id: str
) -> None:
    await sock.send_json(
        {
            "type": "agent_status",
            "phase": phase,
            "tool": tool,
            "turn_id": turn_id,
        }
    )


async def _agent_free_talk_reply(
    sock: WebSocket,
    providers: Providers,
    config: Settings,
    text: str,
    *,
    turn_id: str,
    conversation_id: str,
    store: Store,
    clock: SystemClock,
    concepts: list[Any],
    lock: asyncio.Lock,
    cache: TTSCache,
    agent_loop: AgentLoop,
    tone_hint: str = "",
    memory_context: str = "",
) -> None:
    history = [
        AgentMessage(role=row["role"], content=row["text"])
        for row in store.recent_conversation_messages(
            conversation_id, MAX_HISTORY_MESSAGES
        )
    ]
    brief = build_free_talk_brief(
        today=clock.today(),
        progress=_progress_payload(store, concepts),
        history=history,
        tone_hint=tone_hint,
        memory_context=memory_context,
    )
    result = await agent_loop.run(
        brief,
        text,
        on_status=lambda phase, tool: _send_agent_status(
            sock, phase, tool, turn_id
        ),
    )
    if result.fallback_reason == "model_error":
        await _error(sock, "llm", "模型调用失败，请再试一次")
        return
    reply = result.content.strip()
    if not reply:
        await _error(sock, "llm", "模型没有返回内容")
        return

    sources = list(result.sources)
    used_retrieval = any(
        item.tool in {TOOL_SEARCH_MATERIALS, TOOL_SEARCH_WEB, TOOL_READ_CONCEPT}
        for item in result.tool_results
    )
    mode = "teach" if used_retrieval else "chat"
    web_status = _agent_web_status(result.tool_results)
    store.append_conversation_message(
        conversation_id=conversation_id,
        role="user",
        text=text,
        created_at=clock.now(),
    )
    store.append_conversation_message(
        conversation_id=conversation_id,
        role="assistant",
        text=reply,
        mode=mode,
        sources=sources or None,
        created_at=clock.now(),
    )
    await sock.send_json(
        {
            "type": "reply",
            "conversation_id": conversation_id,
            "text": reply,
            "mode": mode,
            "sources": sources,
            "grounded": bool(sources),
            "web_status": web_status,
            "agent": {
                "tool_calls": result.tool_calls,
                "web_calls": result.web_calls,
                "budget_exhausted": result.budget_exhausted,
            },
            "turn_id": turn_id,
        }
    )
    await _stream_feedback(sock, providers, cache, reply, lock)


REPEAT_COMMANDS = frozenset(
    {"重复", "重复一遍", "再读一遍", "再说一遍", "再念一遍"}
)


def _is_repeat_command(text: Any) -> bool:
    return str(text or "").strip() in REPEAT_COMMANDS


async def _handle_repeat(
    sock: WebSocket,
    agent: Agent,
    store: Store,
    clock: SystemClock,
    cache: TTSCache,
    lock: asyncio.Lock,
    message: dict[str, Any],
) -> None:
    session_id = str(message.get("session_id") or "")
    question_id = message.get("question_id")
    if not session_id or not isinstance(question_id, int):
        await _error(sock, "protocol", "repeat 需要 session_id 与 question_id")
        return
    agent_session = store.agent_session(session_id)
    if (
        agent_session is None
        or agent_session["status"] != "active"
        or agent_session["date"] != clock.today()
    ):
        await _error(sock, "session", "会话已结束或已过期")
        return
    current = agent.current_question(session_id)
    if current is None or current["id"] != question_id:
        await _error(sock, "session", "只能重复当前题")
        return
    await sock.send_json(_question_event(store, session_id, current))
    await _send_question_audio(
        sock, cache, str(current["question_text"]), lock
    )


async def _handle_teach(
    sock: WebSocket,
    agent: Agent,
    agent_loop: AgentLoop,
    store: Store,
    concepts: list[Any],
    clock: SystemClock,
    message: dict[str, Any],
    providers: Providers,
    cache: TTSCache,
    lock: asyncio.Lock,
    teach_state: dict[str, Any],
    emotion: EmotionUpdater | None = None,
) -> None:
    session_id = str(message.get("session_id") or "")
    question_id = message.get("question_id")
    text = str(message.get("text") or "").strip()
    intent = str(message.get("intent") or "teach")
    turn_id = str(message.get("turn_id") or "")

    if not session_id or not isinstance(question_id, int) or not text:
        await _error(
            sock, "protocol", "提问需要 session_id、question_id 与非空 text"
        )
        return
    if intent not in ("teach", "clarify"):
        intent = "teach"

    agent_session = store.agent_session(session_id)
    if (
        agent_session is None
        or agent_session["status"] != "active"
        or agent_session["date"] != clock.today()
    ):
        await _error(sock, "session", "会话已结束或已过期")
        return

    question = store.question(question_id)
    if question is None or question["session_id"] != session_id:
        await _error(sock, "session", "题目不存在或不属于该会话")
        return
    if question["score"] is not None or (question.get("answer_text") or "").strip():
        await _error(sock, "session", "这道题已经作答，先看反馈")
        return

    current = agent.current_question(session_id)
    if current is None or current["id"] != question_id:
        await _error(sock, "session", "只能问当前题")
        return

    questions = store.session_questions(session_id)
    question_index = next(
        (
            index
            for index, row in enumerate(questions, start=1)
            if row["id"] == question_id
        ),
        0,
    )
    if question_index == 0:
        await _error(sock, "session", "题目不存在或不属于该会话")
        return

    concept = _concept_by_id(concepts, question.get("concept_id"))
    last_scored = next(
        (
            row
            for row in reversed(questions)
            if row["id"] != question_id and row["score"] is not None
        ),
        None,
    )
    if teach_state.get("question_id") != question_id:
        teach_state["question_id"] = question_id
        teach_state["messages"] = []
    history = tuple(teach_state["messages"][-6:])

    tone_hint = ""
    if emotion is not None:
        state = await emotion.update(
            text, [(message.role, message.content) for message in history]
        )
        tone_hint = emotion_tone_hint(state)
        await sock.send_json(
            {
                "type": "emotion",
                "comfort": round(state.comfort, 3),
                "energy": round(state.energy, 3),
                "tone": tone_hint,
            }
        )

    session = session_payload(
        session_id,
        str(agent_session["kind"]),
        question_index,
        len(questions),
    )
    builder = build_teach_brief if intent == "teach" else build_clarify_brief
    brief = builder(
        today=clock.today(),
        session=session,
        question=question,
        concept=concept,
        last_scored=last_scored,
        progress=_progress_payload(store, concepts),
        history=history,
        tone_hint=tone_hint,
    )
    result = await agent_loop.run(
        brief,
        text,
        on_status=lambda phase, tool: _send_agent_status(
            sock, phase, tool, turn_id
        ),
    )

    if result.fallback_reason == "model_error":
        await sock.send_json(
            {
                "type": "warning",
                "stage": "llm",
                "message": "模型暂时不可用，先按概念定义讲",
            }
        )

    teach_state["messages"].extend(
        [
            AgentMessage(role="user", content=text),
            AgentMessage(role="assistant", content=result.content),
        ]
    )
    teach_state["messages"] = teach_state["messages"][-6:]

    await sock.send_json(
        {
            "type": "teach_reply",
            "session_id": session_id,
            "question_id": question_id,
            "mode": intent,
            "text": result.content,
            "sources": list(result.sources),
            "turn_id": turn_id,
        }
    )
    await _stream_feedback(
        sock, providers, cache, result.content, lock, utterance="teach"
    )


def _reveal_text(row: dict[str, Any]) -> str:
    """取这道题的参考答案；没有就用评分要点。只读，不评分。"""
    feedback = str(row.get("feedback") or "").strip()
    if feedback and "参考答案：" in feedback:
        return feedback.split("参考答案：", 1)[1].strip()
    try:
        rubric = json.loads(row.get("rubric_json") or "{}")
    except json.JSONDecodeError:
        rubric = {}
    if not isinstance(rubric, dict):
        rubric = {}
    for key in ("reference_answer", "criteria", "explanation"):
        value = str(rubric.get(key) or "").strip()
        if value:
            return value
    must_have = rubric.get("must_have") or []
    if isinstance(must_have, list) and must_have:
        return "；".join(str(item).strip() for item in must_have if str(item).strip())
    return ""


async def _handle_reveal(
    sock: WebSocket, store: Store, clock: SystemClock, message: dict[str, Any]
) -> None:
    session_id = str(message.get("session_id") or "")
    question_id = message.get("question_id")
    if not session_id or not isinstance(question_id, int):
        await _error(sock, "protocol", "reveal 需要 session_id 与 question_id")
        return
    agent_session = store.agent_session(session_id)
    if agent_session is None or agent_session["date"] != clock.today():
        await _error(sock, "session", "会话已结束或已过期")
        return
    row = store.question(question_id)
    if row is None or row["session_id"] != session_id:
        await _error(sock, "session", "题目不存在或不属于该会话")
        return
    await sock.send_json(
        {
            "type": "reveal",
            "question_id": question_id,
            "text": _reveal_text(row),
        }
    )


async def _handle_answer(
    sock: WebSocket,
    agent: Agent,
    store: Store,
    message: dict[str, Any],
    providers: Providers,
    cache: TTSCache,
    lock: asyncio.Lock,
    on_settled: Callable[[Settlement], None] | None = None,
) -> None:
    session_id = str(message.get("session_id") or "")
    question_id = message.get("question_id")
    text = str(message.get("text") or "").strip()
    turn_id = message.get("turn_id")
    input_mode = str(message.get("input_mode") or "text")
    retry = bool(message.get("retry"))

    if not session_id or not isinstance(question_id, int) or not text:
        await _error(sock, "protocol", "answer 需要 session_id、question_id 与非空 text")
        return

    try:
        turn = await agent.submit(
            session_id, question_id, text, input_mode=input_mode, retry=retry
        )
    except SessionAlreadyFinalized as exc:
        await sock.send_json(
            {
                "type": "error",
                "stage": "session",
                "code": "session_finished",
                "message": str(exc),
            }
        )
        return
    except (KeyError, ValueError) as exc:
        await _error(sock, "session", str(exc))
        return

    await _send_turn(
        sock,
        store,
        turn,
        session_id=session_id,
        turn_id=str(turn_id) if turn_id else None,
        providers=providers,
        cache=cache,
        lock=lock,
        on_settled=on_settled,
    )


async def _handle_audio(
    sock: WebSocket,
    providers: Providers,
    config: Settings,
    agent: Agent,
    store: Store,
    message: dict[str, Any],
    cache: TTSCache,
    lock: asyncio.Lock,
    on_settled: Callable[[Settlement], None] | None = None,
) -> None:
    session_id = str(message.get("session_id") or "")
    question_id = message.get("question_id")
    turn_id = str(message.get("turn_id") or "")
    if not session_id or not isinstance(question_id, int):
        await _error(sock, "protocol", "audio 需要 session_id 与 question_id")
        return

    try:
        raw, sample_rate = _audio_bytes(message)
    except ValueError as exc:
        await _error(sock, "asr", str(exc))
        return

    try:
        result = await providers.asr.transcribe(
            ASRRequest(
                audio=raw,
                mime=str(message.get("mime") or "audio/wav"),
                sample_rate=sample_rate,
                language=config.asr_language,
            )
        )
    except ProviderError as exc:
        try:
            agent.fallback_to_text(session_id, question_id)
        except KeyError:
            pass
        await _error(sock, "asr", f"{exc}；请改用文字回答")
        return

    text = result.text.strip()
    reason = None
    if is_suspicious(text):
        reason = "suspicious"
    elif is_mixed(text):
        reason = "mixed"

    await sock.send_json(
        {
            "type": "transcript",
            "turn_id": turn_id,
            "text": text,
            "confidence": result.confidence,
            "needs_confirmation": reason is not None,
            "reason": reason,
        }
    )
    if reason is not None:
        return

    try:
        turn = await agent.submit(
            session_id,
            question_id,
            text,
            input_mode="voice",
            retry=bool(message.get("retry")),
        )
    except (KeyError, ValueError, SessionAlreadyFinalized) as exc:
        await _error(sock, "session", str(exc))
        return

    await _send_turn(
        sock,
        store,
        turn,
        session_id=session_id,
        turn_id=turn_id,
        providers=providers,
        cache=cache,
        lock=lock,
        on_settled=on_settled,
    )


async def _error(sock: WebSocket, stage: str, message: str) -> None:
    await sock.send_json({"type": "error", "stage": stage, "message": message})


app = create_app()
