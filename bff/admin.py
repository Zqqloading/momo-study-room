"""管理后台 API：只读查询 + 材料上传 + 长任务提交/轮询。

除 `POST /api/admin/uploads` 与 `POST /api/admin/tasks` 外全部 GET。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from core.admin_queries import (
    AdminListError,
    concept_detail,
    conversation_detail,
    health as build_health,
    list_bank_questions,
    list_concepts,
    list_conversations,
    list_materials,
    list_pipeline_runs,
    list_session_questions,
    list_sessions,
    material_detail,
    pipeline_run_detail,
    question_detail,
    scan_materials,
    search as run_search,
    session_detail,
)
from core.admin_tasks import (
    TaskParamError,
    create_task,
    get_task,
    list_tasks,
)

router = APIRouter(prefix="/api/admin")


def _context(request: Request) -> tuple[Any, Any, Any]:
    return (
        request.app.state.store,
        request.app.state.settings,
        request.app.state.providers,
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_FILES = 10


def _safe_upload_name(raw: str) -> str:
    base = raw.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not base or base in (".", ".."):
        raise ValueError("文件名不合法")
    if not base.lower().endswith((".md", ".html")):
        raise ValueError("只支持 .md / .html")
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", base).strip(" .")
    if not cleaned:
        raise ValueError("文件名不合法")
    return cleaned


def _not_found(message: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": message})


def _bad_request(message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": message})


@router.get("/health")
async def health(request: Request, response: Response) -> Any:
    _no_store(response)
    store, settings, providers = _context(request)
    return build_health(
        store.conn,
        db_path=settings.db_path,
        provider={
            "fake": providers.any_fake,
            "modes": providers.modes,
            "notes": providers.notes,
        },
        embedding_model=settings.embedding.model,
        embedding_dim=settings.embedding_dim,
    )


@router.get("/search")
async def search(
    request: Request,
    response: Response,
    q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=100),
) -> Any:
    _no_store(response)
    store, _settings, _providers = _context(request)
    return run_search(
        store.conn, request.app.state.concepts, q, limit=limit
    )


def _list_response(
    request: Request, response: Response, builder: Any, **kwargs: Any
) -> Any:
    response.headers["Cache-Control"] = "no-store"
    store, _settings, _providers = _context(request)
    try:
        return builder(store.conn, **kwargs)
    except AdminListError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@router.get("/materials")
async def materials_list(
    request: Request,
    response: Response,
    q: str | None = None,
    status: str | None = None,
    format: str | None = None,
    ids: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    sort: str | None = None,
    order: str | None = None,
) -> Any:
    return _list_response(
        request,
        response,
        list_materials,
        q=q,
        status=status,
        format=format,
        ids=ids,
        page=page,
        per_page=per_page,
        sort=sort,
        order=order,
    )


@router.get("/materials/scan")
async def materials_scan(request: Request, response: Response) -> Any:
    _no_store(response)
    store, settings, _providers = _context(request)
    return scan_materials(store.conn, settings.content_dir)


@router.get("/concepts")
async def concepts_list(
    request: Request,
    response: Response,
    q: str | None = None,
    status: str | None = None,
    mastery: int | None = None,
    ids: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    sort: str | None = None,
    order: str | None = None,
) -> Any:
    response.headers["Cache-Control"] = "no-store"
    store, _settings, _providers = _context(request)
    try:
        return list_concepts(
            store.conn,
            request.app.state.concepts,
            q=q,
            status=status,
            mastery=mastery,
            ids=ids,
            page=page,
            per_page=per_page,
            sort=sort,
            order=order,
        )
    except AdminListError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@router.get("/bank-questions")
async def bank_questions_list(
    request: Request,
    response: Response,
    q: str | None = None,
    concept_id: str | None = None,
    kind: str | None = None,
    ids: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    sort: str | None = None,
    order: str | None = None,
) -> Any:
    return _list_response(
        request,
        response,
        list_bank_questions,
        q=q,
        concept_id=concept_id,
        kind=kind,
        ids=ids,
        page=page,
        per_page=per_page,
        sort=sort,
        order=order,
    )


@router.get("/session-questions")
async def session_questions_list(
    request: Request,
    response: Response,
    q: str | None = None,
    session_id: str | None = None,
    concept_id: str | None = None,
    question_bank_id: str | None = None,
    min_score: int | None = None,
    max_score: int | None = None,
    ids: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    sort: str | None = None,
    order: str | None = None,
) -> Any:
    return _list_response(
        request,
        response,
        list_session_questions,
        q=q,
        session_id=session_id,
        concept_id=concept_id,
        question_bank_id=question_bank_id,
        min_score=min_score,
        max_score=max_score,
        ids=ids,
        page=page,
        per_page=per_page,
        sort=sort,
        order=order,
    )


@router.get("/sessions")
async def sessions_list(
    request: Request,
    response: Response,
    q: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    concept_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    ids: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    sort: str | None = None,
    order: str | None = None,
) -> Any:
    return _list_response(
        request,
        response,
        list_sessions,
        q=q,
        status=status,
        kind=kind,
        concept_id=concept_id,
        start=start,
        end=end,
        ids=ids,
        page=page,
        per_page=per_page,
        sort=sort,
        order=order,
    )


@router.get("/conversations")
async def conversations_list(
    request: Request,
    response: Response,
    q: str | None = None,
    start: str | None = None,
    end: str | None = None,
    ids: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    sort: str | None = None,
    order: str | None = None,
) -> Any:
    return _list_response(
        request,
        response,
        list_conversations,
        q=q,
        start=start,
        end=end,
        ids=ids,
        page=page,
        per_page=per_page,
        sort=sort,
        order=order,
    )


@router.get("/pipeline-runs")
async def pipeline_runs_list(
    request: Request,
    response: Response,
    kind: str | None = None,
    status: str | None = None,
    start: str | None = None,
    end: str | None = None,
    ids: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    sort: str | None = None,
    order: str | None = None,
) -> Any:
    return _list_response(
        request,
        response,
        list_pipeline_runs,
        kind=kind,
        status=status,
        start=start,
        end=end,
        ids=ids,
        page=page,
        per_page=per_page,
        sort=sort,
        order=order,
    )


@router.get("/pipeline-runs/{run_id}")
async def pipeline_run(request: Request, run_id: int, response: Response) -> Any:
    response.headers["Cache-Control"] = "no-store"
    store, _settings, _providers = _context(request)
    result = pipeline_run_detail(store.conn, run_id)
    if result is None:
        return _not_found(f"管线运行不存在：{run_id}")
    return result


@router.get("/material/{material_id}")
async def material(
    request: Request,
    response: Response,
    material_id: str,
    history: bool = False,
) -> Any:
    _no_store(response)
    store, settings, _providers = _context(request)
    result = material_detail(
        store.conn,
        request.app.state.concepts,
        material_id,
        history=history,
        db_path=settings.db_path,
        content_dir=settings.content_dir,
    )
    if result is None:
        return _not_found(f"材料不存在：{material_id}")
    return result


@router.get("/concept/{concept_id}")
async def concept(
    request: Request, response: Response, concept_id: str
) -> Any:
    _no_store(response)
    store, settings, _providers = _context(request)
    result = concept_detail(
        store.conn,
        request.app.state.concepts,
        concept_id,
        db_path=settings.db_path,
        content_dir=settings.content_dir,
    )
    if result is None:
        return _not_found(f"概念不存在：{concept_id}")
    return result


@router.get("/question")
async def question(
    request: Request,
    response: Response,
    bank_id: str | None = None,
    session_question_id: int | None = None,
) -> Any:
    _no_store(response)
    if (bank_id is None) == (session_question_id is None):
        return _bad_request("bank_id 与 session_question_id 必须二选一")
    store, settings, _providers = _context(request)
    result = question_detail(
        store.conn,
        request.app.state.concepts,
        bank_id=bank_id,
        session_question_id=session_question_id,
        db_path=settings.db_path,
        content_dir=settings.content_dir,
    )
    if result is None:
        return _not_found("题目不存在")
    return result


@router.get("/session/{session_id}")
async def session(
    request: Request, response: Response, session_id: str
) -> Any:
    _no_store(response)
    store, _settings, _providers = _context(request)
    result = session_detail(
        store.conn, request.app.state.concepts, session_id
    )
    if result is None:
        return _not_found(f"会话不存在：{session_id}")
    return result


@router.get("/conversation/{conversation_id}")
async def conversation(
    request: Request, response: Response, conversation_id: str
) -> Any:
    _no_store(response)
    store, _settings, _providers = _context(request)
    result = conversation_detail(store.conn, conversation_id)
    if result is None:
        return _not_found(f"自由对话不存在：{conversation_id}")
    return result


@router.post("/uploads")
async def upload_materials(
    request: Request,
    response: Response,
    files: list[UploadFile] = File(...),
) -> Any:
    _no_store(response)
    _store, settings, _providers = _context(request)
    if len(files) > MAX_UPLOAD_FILES:
        return _bad_request(f"一次最多上传 {MAX_UPLOAD_FILES} 个文件")
    inbox = Path(settings.content_dir) / "materials" / "inbox"
    try:
        inbox.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return JSONResponse(
            status_code=500, content={"error": f"创建 inbox 失败：{exc}"}
        )

    payload: list[tuple[str, bytes]] = []
    names: set[str] = set()
    for file in files:
        try:
            name = _safe_upload_name(file.filename or "")
        except ValueError as exc:
            return JSONResponse(
                status_code=400, content={"error": str(exc), "field": "file"}
            )
        if name in names:
            return _bad_request(f"同一次上传里有重名文件：{name}")
        names.add(name)
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error": f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB：{name}"},
            )
        if not data:
            return _bad_request(f"文件为空：{name}")
        payload.append((name, data))

    for name, _data in payload:
        if (inbox / name).exists():
            return JSONResponse(
                status_code=409,
                content={
                    "error": f"文件已存在：materials/inbox/{name}",
                    "field": "file",
                },
            )

    written: list[Path] = []
    try:
        for name, data in payload:
            target = inbox / name
            with target.open("xb") as handle:
                handle.write(data)
            written.append(target)
    except OSError as exc:
        for target in written:
            target.unlink(missing_ok=True)
        return JSONResponse(
            status_code=500, content={"error": f"写入文件失败：{exc}"}
        )

    return {
        "files": [
            {
                "name": name,
                "path": f"materials/inbox/{name}",
                "size": len(data),
            }
            for name, data in payload
        ]
    }


@router.post("/tasks")
async def submit_task(request: Request, payload: dict[str, Any]) -> Any:
    store, _settings, _providers = _context(request)
    try:
        task, created = create_task(
            store.conn,
            kind=payload.get("kind"),
            params=payload.get("params", {}),
        )
    except TaskParamError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc), "field": exc.field},
        )
    runner = getattr(request.app.state, "task_runner", None)
    if created and runner is not None:
        await runner.submit(task["task_id"])
    return JSONResponse(
        status_code=202 if created else 200,
        content={"task_id": task["task_id"], "status": task["status"]},
    )


@router.get("/tasks")
async def tasks(
    request: Request,
    response: Response,
    kind: str | None = None,
    status: str | None = None,
    start: str | None = None,
    end: str | None = None,
    ids: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    sort: str | None = None,
    order: str | None = None,
) -> Any:
    response.headers["Cache-Control"] = "no-store"
    store, _settings, _providers = _context(request)
    try:
        return list_tasks(
            store.conn,
            kind=kind,
            status=status,
            start=start,
            end=end,
            ids=ids,
            page=page,
            per_page=per_page,
            sort=sort,
            order=order,
        )
    except TaskParamError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc), "field": exc.field},
        )


@router.get("/tasks/{task_id}")
async def task(request: Request, task_id: str, response: Response) -> Any:
    response.headers["Cache-Control"] = "no-store"
    store, _settings, _providers = _context(request)
    result = get_task(store.conn, task_id)
    if result is None:
        return _not_found(f"任务不存在：{task_id}")
    return result
