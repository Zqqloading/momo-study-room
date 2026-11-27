from __future__ import annotations

import asyncio
from datetime import datetime

from bff.config import load_settings
from bff.probe import render_markdown, run_probes, write_report

WHEN = datetime(2026, 11, 21, 15, 0)


def test_deepseek_tts_declares_no_streaming() -> None:
    from bff.config import Endpoint
    from bff.providers.deepseek_tts import DeepSeekTTS

    tts = DeepSeekTTS(
        Endpoint(label="DeepSeek TTS", base_url="https://example.com"),
        timeout=1,
    )
    assert tts.supports_streaming is False


def test_fake_probe_covers_four_providers_and_is_marked_unverified() -> None:
    settings = load_settings({"PROVIDER_MODE": "fake"})
    results = asyncio.run(run_probes(settings, repeat=2))

    assert {result.provider for result in results} == {
        "MiMo LLM",
        "MiMo ASR",
        "Breeze TTS",
        "DeepSeek Flash",
    }
    assert all(result.ok for result in results)
    assert all(result.mode == "fake" for result in results)

    markdown = render_markdown(settings, results, WHEN)
    assert "离线假模式" in markdown
    assert "不能写进冻结规格" in markdown
    assert "Breeze TTS" in markdown


def test_probe_writes_markdown_and_json(tmp_path) -> None:
    settings = load_settings({"PROVIDER_MODE": "fake"})
    results = asyncio.run(run_probes(settings, repeat=2))
    md_path, json_path = write_report(settings, results, out_dir=tmp_path, when=WHEN)

    assert md_path.exists() and json_path.exists()
    assert "2026-11-21-1500" in md_path.name
    assert '"results"' in json_path.read_text(encoding="utf-8")
