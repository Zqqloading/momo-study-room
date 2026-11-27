from __future__ import annotations

import asyncio
from datetime import datetime

from bff.emotion import EmotionUpdater
from bff.providers.fake import FakeScorer
from core.db import connect, init_schema
from core.emotion import Emotion
from core.store import Store

NOW = datetime(2026, 11, 26, 10, 0, 0)


class _ScriptedScorer:
    name = "scripted-emotion"

    def __init__(self, payload: str, *, delay: float = 0.0) -> None:
        self.payload = payload
        self.delay = delay
        self.calls: list[tuple[str, str]] = []

    async def grade(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.payload


def _updater(scorer, timeout: float = 0.8) -> tuple[EmotionUpdater, Store]:
    store = Store(connect(":memory:"))
    init_schema(store.conn)
    updater = EmotionUpdater(
        store,
        scorer,
        timeout_seconds=timeout,
        now=lambda: NOW,
    )
    return updater, store


def test_update_applies_delta_and_persists() -> None:
    scorer = _ScriptedScorer(
        '{"comfort_delta":0.2,"energy_delta":-0.1,"intense":false}'
    )
    updater, store = _updater(scorer)
    try:
        state = asyncio.run(updater.update("今天有点累"))
        assert state == Emotion(0.2, 0.4)
        assert updater.current() == Emotion(0.2, 0.4)
        row = store.emotion_state("owner", "learner", now="2026-11-26T10:00:00")
        assert (row["comfort"], row["energy"]) == (0.2, 0.4)
        assert len(scorer.calls) == 1
        assert "今天有点累" in scorer.calls[0][1]
    finally:
        store.close()


def test_non_intense_delta_is_capped_at_three_tenths() -> None:
    scorer = _ScriptedScorer(
        '{"comfort_delta":0.5,"energy_delta":-0.9,"intense":false}'
    )
    updater, store = _updater(scorer)
    try:
        assert asyncio.run(updater.update("太好了")) == Emotion(0.3, 0.2)
    finally:
        store.close()


def test_intense_delta_can_exceed_three_tenths() -> None:
    scorer = _ScriptedScorer(
        '{"comfort_delta":-0.8,"energy_delta":0.8,"intense":true}'
    )
    updater, store = _updater(scorer)
    try:
        assert asyncio.run(updater.update("我快崩溃了")) == Emotion(-0.8, 1.0)
    finally:
        store.close()


def test_timeout_uses_old_state_without_writing() -> None:
    scorer = _ScriptedScorer(
        '{"comfort_delta":0.5,"energy_delta":0.5}', delay=0.05
    )
    updater, store = _updater(scorer, timeout=0.001)
    try:
        assert asyncio.run(updater.update("今天好累")) == Emotion(0.0, 0.5)
        row = store.emotion_state("owner", "learner", now="2026-11-26T10:00:00")
        assert (row["comfort"], row["energy"]) == (0.0, 0.5)
    finally:
        store.close()


def test_invalid_json_degrades_to_zero_delta() -> None:
    updater, store = _updater(_ScriptedScorer("不是 JSON"))
    try:
        assert asyncio.run(updater.update("随便聊聊")) == Emotion(0.0, 0.5)
    finally:
        store.close()


def test_fake_scorer_yields_zero_delta() -> None:
    updater, store = _updater(FakeScorer())
    try:
        assert asyncio.run(updater.update("今天好累")) == Emotion(0.0, 0.5)
    finally:
        store.close()


def test_concurrent_updates_do_not_lose_writes() -> None:
    scorer = _ScriptedScorer(
        '{"comfort_delta":0.3,"energy_delta":0.2,"intense":false}', delay=0.01
    )
    updater, store = _updater(scorer)
    try:
        async def run_both() -> list[Emotion]:
            return await asyncio.gather(
                updater.update("第一条"),
                updater.update("第二条"),
            )

        asyncio.run(run_both())
        row = store.emotion_state("owner", "learner", now="2026-11-26T10:00:00")
        assert (row["comfort"], row["energy"]) == (0.6, 0.9)
    finally:
        store.close()


def test_event_payload_includes_tone_and_midpoint() -> None:
    updater, store = _updater(_ScriptedScorer("{}"))
    try:
        payload = updater.event_payload()
        assert payload == {
            "comfort": 0.0,
            "energy": 0.5,
            "tone": "语气平稳自然。",
        }
    finally:
        store.close()
