"""开场讲解的编排：一次 LLM 调用，失败退回概念定义。"""

from __future__ import annotations

import logging
from typing import Any

from core.lecture import build_lecture_messages, fallback_lecture, parse_lecture
from core.ports import JsonScorer

logger = logging.getLogger(__name__)


async def generate_lecture(scorer: JsonScorer, concept: Any) -> str:
    if concept is None:
        return ""
    system, user = build_lecture_messages(concept)
    try:
        raw = await scorer.grade(system, user)
    except Exception:
        logger.warning("lecture_failed", exc_info=True)
        return fallback_lecture(concept)
    try:
        return parse_lecture(raw) or fallback_lecture(concept)
    except Exception:
        logger.warning("lecture_parse_failed", exc_info=True)
        return fallback_lecture(concept)
