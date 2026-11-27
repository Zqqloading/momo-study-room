"""答题记录：最近 N 小时已评分的题，只读。

前端右上角「答题记录」抽屉用它；时间窗只是查询过滤，不删任何数据。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/history")

MAX_HOURS = 24 * 7
MAX_ITEMS = 100


def _cutoff(hours: int) -> str:
    return (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")


@router.get("/answers")
async def answers(request: Request, hours: int = 24, limit: int = 50) -> Any:
    hours = max(1, min(hours, MAX_HOURS))
    limit = max(1, min(limit, MAX_ITEMS))
    try:
        store = request.app.state.store
        concepts = request.app.state.concepts
        names = {concept.id: concept.name for concept in concepts}
        rows = store.answered_questions_since(_cutoff(hours), limit=limit)
        return {
            "hours": hours,
            "items": [
                {
                    "question_id": row["id"],
                    "session_id": row["session_id"],
                    "session_date": row["session_date"],
                    "session_kind": row["session_kind"],
                    "concept_id": row["concept_id"],
                    "concept_name": names.get(str(row["concept_id"] or ""), ""),
                    "question_type": row["question_type"],
                    "question_text": row["question_text"],
                    "answer_text": row["answer_text"] or "",
                    "score": row["score"],
                    "feedback": row["feedback"] or "",
                    "answered_at": row["created_at"],
                }
                for row in rows
            ],
        }
    except Exception as exc:  # pragma: no cover - 保持 500 的 JSON 形状
        return JSONResponse(status_code=500, content={"error": str(exc)})
