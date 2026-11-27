"""知识库只读接口：今日单元提议与掌握程度总览。

两个接口都不写库、不调 provider、不生成题目；前端面板只依赖这里的数据。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.coach import Coach
from core.models import UnitProposal
from core.progress import build_overview

router = APIRouter(prefix="/api/kb")


def _proposal_payload(proposal: UnitProposal) -> dict[str, Any]:
    payload = asdict(proposal)
    payload["slots"] = [
        {
            "slot": slot.slot,
            "type": slot.question_type,
            "label": slot.label,
            "role": slot.role,
            "concept_id": slot.concept_id,
        }
        for slot in proposal.slots
    ]
    return payload


@router.get("/unit/proposal")
async def unit_proposal(request: Request) -> Any:
    try:
        coach: Coach = request.app.state.coach
        return _proposal_payload(coach.propose())
    except Exception as exc:  # pragma: no cover - 保持 500 的 JSON 形状
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/overview")
async def overview(request: Request) -> Any:
    try:
        store = request.app.state.store
        concepts = request.app.state.concepts
        clock = request.app.state.clock
        states = store.concept_states()
        active_ids = [state.id for state in states if state.status == "active"]
        assessments = store.latest_concept_assessments(active_ids)
        return asdict(
            build_overview(
                concepts,
                states,
                store.recent_units(),
                clock.today(),
                assessments,
            )
        )
    except Exception as exc:  # pragma: no cover - 保持 500 的 JSON 形状
        return JSONResponse(status_code=500, content={"error": str(exc)})
