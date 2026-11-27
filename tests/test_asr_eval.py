from __future__ import annotations

import asyncio

from bff.asr_eval import Row, evaluate, parse_manifest, summarize
from core.ports import ASRResult

MANIFEST_SAMPLE = """# 清单

| # | 建议文本 | 目标术语 | 音频路径 | 时长 | 设备 | 环境 |
|---|---|---|---|---|---|---|
| 01 | 用你自己的话说说 agent 是什么 | agent | audio/01.wav | | | |
| 02 | workflow 和 agent 的区别 | workflow、agent | audio/02.wav | | | |
| 03 | ReAct 是做什么的 | ReAct | audio/03.wav | | | |
"""


def test_parse_manifest_reads_rows_and_targets() -> None:
    rows = parse_manifest(MANIFEST_SAMPLE)
    assert [row.number for row in rows] == ["01", "02", "03"]
    assert rows[1].targets == ("workflow", "agent")
    assert rows[2].targets == ("ReAct",)
    assert rows[0].audio == "audio/01.wav"


class _StubASR:
    name = "stub"
    text = "agent 就是能自己决定下一步的程序，workflow 是人写死的"

    async def transcribe(self, request):
        return ASRResult(text=self.text, confidence=0.9, latency_ms=1)


class _Providers:
    asr = _StubASR()


def _fake_recorded_row(number: str, targets: tuple[str, ...]) -> Row:
    row = Row(number=number, text="", targets=targets, audio="audio/01.wav")
    row.audio_path.parent.mkdir(parents=True, exist_ok=True)
    if not row.audio_path.exists():
        row.audio_path.write_bytes(b"RIFF")
    return row


def test_evaluate_matches_terms_and_marks_missing(tmp_path, monkeypatch) -> None:
    import bff.asr_eval as module

    monkeypatch.setattr(module, "TEST_SET_DIR", tmp_path)
    rows = [
        _fake_recorded_row("01", ("agent", "workflow")),
        _fake_recorded_row("02", ("ReAct",)),
    ]
    results = asyncio.run(evaluate(_Providers(), rows))  # type: ignore[arg-type]

    assert results[0].passed is True
    assert results[0].matched == ("agent", "workflow")
    assert results[1].passed is False
    assert results[1].missing == ("ReAct",)


def test_summarize_uses_term_level_rate() -> None:
    from bff.asr_eval import UtteranceResult

    rows = [Row("01", "", ("agent", "workflow"), ""), Row("02", "", ("ReAct",), "")]
    results = [
        UtteranceResult(rows[0], "agent 和 workflow", ("agent", "workflow"), (), 1),
        UtteranceResult(rows[1], "react 是什么", ("ReAct",), (), 1),
    ]
    summary = summarize(results)
    assert summary["terms"] == 3
    assert summary["hits"] == 3
    assert summary["rate"] == 1.0
    assert summary["passed"] is True
