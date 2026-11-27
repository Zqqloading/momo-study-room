"""d0a：四个外部 API 的连通性 / 延迟探针。

用法（项目根目录）：
    python -m bff.probe                 # 按 .env 的 PROVIDER_MODE
    python -m bff.probe --mode real     # 强制真实调用，缺配置就报错
    python -m bff.probe --repeat 5      # 评分 JSON 稳定性多次采样

结果写到 docs/designs/api-probe/<日期-时间>.md 和 .json，并把摘要打到终端。
真实结果才可用于填写冻结规格的"待定区"；fake 模式会被明确标注为未验证。
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.ports import ASRRequest, ChatMessage
from core.persona import PERSONA_NAME
from core.scoring import SCORE_SCHEMA_HINT, parse_score_result

from .config import MODE_FAKE, PROJECT_ROOT, Settings, load_settings
from .media import mime_for_path
from .providers.base import ProviderNotConfigured
from .providers.fake import synthesize_tone_wav
from .providers.registry import Providers, build_providers

PROBE_OUT_DIR = PROJECT_ROOT / "docs" / "designs" / "api-probe"
ASR_SAMPLE_DIR = PROJECT_ROOT / "docs" / "designs" / "asr-test-set" / "audio"

SCORER_SYSTEM_PROMPT = (
    "你是学习伴侣的评分器。根据 rubric 给回答打分，严格按给定 JSON 形状返回。\n"
    + SCORE_SCHEMA_HINT
)
SCORER_USER_PROMPT = """题目（id=q1，kind=recall）：
用你自己的话说说 agent 和 workflow 的区别。
rubric：0 空白；40 提到正确名词但关系说错；70 方向对但含糊；90 正确且有自己的例子；100 正确、举例且说出边界。
用户回答：
workflow 是人把步骤排好，agent 会自己决定下一步做什么，比如点外卖时它自己选先看哪家店。"""


@dataclass
class ProbeResult:
    provider: str
    adapter: str
    mode: str
    ok: bool
    error: str = ""
    metrics: dict[str, object] = field(default_factory=dict)
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def is_real(self) -> bool:
        return self.mode == "real"


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _adapter_mode(providers: Providers, key: str) -> str:
    return providers.modes.get(key, "unknown")


def _failed(provider: str, adapter: str, mode: str, started: float, exc: Exception) -> ProbeResult:
    return ProbeResult(
        provider=provider,
        adapter=adapter,
        mode=mode,
        ok=False,
        error=str(exc),
        metrics={"total_ms": _ms(started)},
    )


async def probe_llm(providers: Providers) -> ProbeResult:
    messages = [ChatMessage(role="user", content="用一句话解释：agent 和 workflow 的区别。")]
    started = time.perf_counter()
    first_token_ms: int | None = None
    pieces: list[str] = []
    try:
        if getattr(providers.llm, "supports_streaming", False):
            async for piece in providers.llm.stream(messages):
                if first_token_ms is None:
                    first_token_ms = _ms(started)
                pieces.append(piece)
        else:
            pieces.append(await providers.llm.complete(messages))
        text = "".join(pieces).strip()
        if not text:
            raise RuntimeError("模型返回空文本")
        total_ms = _ms(started)
        return ProbeResult(
            provider="MiMo LLM",
            adapter=providers.llm.name,
            mode=_adapter_mode(providers, "llm"),
            ok=True,
            metrics={
                "first_token_ms": first_token_ms,
                "total_ms": total_ms,
                "chars": len(text),
                "chars_per_second": round(len(text) / max(total_ms / 1000, 0.001), 1),
            },
            detail={"text": text[:300]},
        )
    except Exception as exc:
        return _failed(
            "MiMo LLM", getattr(providers.llm, "name", "?"), _adapter_mode(providers, "llm"), started, exc
        )


def _asr_sample() -> tuple[bytes, str, str]:
    """优先用用户录的测试集；没有就合成提示音，并如实标注。"""
    if ASR_SAMPLE_DIR.is_dir():
        files = [p for p in ASR_SAMPLE_DIR.iterdir() if mime_for_path(p) and p.is_file()]
        files.sort(key=lambda p: (p.suffix.lower() not in {".wav", ".mp3"}, p.name))
        for path in files:
            mime = mime_for_path(path)
            return path.read_bytes(), mime, f"测试集样本 {path.name}"
    return synthesize_tone_wav("probe"), "audio/wav", "合成提示音（不是人声，只测链路）"


async def probe_asr(providers: Providers, language: str = "zh") -> ProbeResult:
    audio, mime, source = _asr_sample()
    started = time.perf_counter()
    mode = _adapter_mode(providers, "asr")
    fake_note = "假实现固定返回示例文本，不代表识别质量" if mode == "fake" else ""
    try:
        result = await providers.asr.transcribe(
            ASRRequest(audio=audio, mime=mime, sample_rate=16000, language=language)
        )
        elapsed = _ms(started)
        return ProbeResult(
            provider="MiMo ASR",
            adapter=providers.asr.name,
            mode=mode,
            ok=True,
            metrics={
                "total_ms": elapsed,
                "bytes": len(audio),
                "mime": mime,
                "confidence": result.confidence,
            },
            detail={
                "sample": source,
                "text": result.text or "（空转写）",
                "warning": fake_note or ("" if result.text else "样本里没有人声时返回空转写属正常"),
            },
        )
    except Exception as exc:
        return _failed(
            "MiMo ASR", getattr(providers.asr, "name", "?"), _adapter_mode(providers, "asr"), started, exc
        )


async def probe_tts(providers: Providers) -> ProbeResult:
    text = f"你好，我是 {PERSONA_NAME}，你的学习搭子。今天用你自己的话说说，agent 是什么。"
    started = time.perf_counter()
    try:
        result = await providers.tts.synthesize(text)
        elapsed = _ms(started)
        if not result.audio:
            raise RuntimeError("TTS 返回空音频")

        stream_metrics: dict[str, object] = {}
        if getattr(providers.tts, "supports_streaming", False) and hasattr(providers.tts, "stream"):
            stream_started = time.perf_counter()
            first_chunk_ms: int | None = None
            stream_bytes = 0
            chunks = 0
            try:
                async for chunk in providers.tts.stream(text):
                    if first_chunk_ms is None:
                        first_chunk_ms = _ms(stream_started)
                    stream_bytes += len(chunk)
                    chunks += 1
                stream_metrics = {
                    "stream_first_chunk_ms": first_chunk_ms,
                    "stream_total_ms": _ms(stream_started),
                    "stream_bytes": stream_bytes,
                    "stream_chunks": chunks,
                }
            except Exception as exc:
                stream_metrics = {"stream_error": str(exc)[:160]}

        return ProbeResult(
            provider="Breeze TTS",
            adapter=providers.tts.name,
            mode=_adapter_mode(providers, "tts"),
            ok=True,
            metrics={
                "total_ms": elapsed,
                "first_chunk_ms": result.first_chunk_ms,
                "bytes": len(result.audio),
                "mime": result.mime,
                "supports_streaming": getattr(
                    providers.tts, "supports_streaming", False
                ),
                **stream_metrics,
            },
            detail={"text": text},
        )
    except Exception as exc:
        return _failed(
            "Breeze TTS",
            getattr(providers.tts, "name", "?"),
            _adapter_mode(providers, "tts"),
            started,
            exc,
        )


async def probe_scorer(providers: Providers, repeat: int) -> ProbeResult:
    parsable = 0
    latencies: list[int] = []
    scores: list[int] = []
    errors: list[str] = []
    for _ in range(repeat):
        started = time.perf_counter()
        try:
            raw = await providers.scorer.grade(SCORER_SYSTEM_PROMPT, SCORER_USER_PROMPT)
            parsed = parse_score_result(raw, expected_ids=["q1"])
            latencies.append(_ms(started))
            parsable += 1
            scores.append(parsed.questions[0].score)
        except Exception as exc:  # noqa: BLE001 - 探针要收集所有失败
            latencies.append(_ms(started))
            errors.append(str(exc))

    return ProbeResult(
        provider="DeepSeek Flash",
        adapter=providers.scorer.name,
        mode=_adapter_mode(providers, "scorer"),
        ok=repeat > 0 and parsable == repeat,
        error="；".join(errors[:2]),
        metrics={
            "runs": repeat,
            "parsable": parsable,
            "parse_rate": round(parsable / repeat, 2) if repeat else 0.0,
            "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
            "scores": scores,
        },
        detail={
            "contract": "questions[].score/why/misconception_hit/certain + session_misconception",
            "rule": "任何一次输出不符合契约都判失败；稳定性门槛等 20 条人工对照后再定",
        },
    )


def _mode_line(settings: Settings, results: list[ProbeResult]) -> str:
    fake = [r.provider for r in results if not r.is_real]
    if settings.mode == MODE_FAKE or len(fake) == len(results):
        return "离线假模式：本次没有产生任何真实测量。"
    if fake:
        return f"部分真实：{', '.join(fake)} 仍是假实现，其余为真实调用。"
    return "全部为真实 API 调用。"


def render_markdown(settings: Settings, results: list[ProbeResult], when: datetime) -> str:
    lines: list[str] = []
    lines.append(f"# API 连通性探针 — {when:%Y-%m-%d %H:%M}")
    lines.append("")
    lines.append(f"- 配置模式：`{settings.mode}`")
    lines.append(f"- {_mode_line(settings, results)}")
    if any(not r.is_real for r in results):
        lines.append("")
        lines.append("> 假实现的结果不能写进冻结规格的待定区，只能证明链路形状。")
    lines.append("")
    lines.append("| 服务 | 适配器 | 模式 | 结果 | 关键指标 |")
    lines.append("|---|---|---|---|---|")
    for result in results:
        metrics = "，".join(f"{key}={value}" for key, value in result.metrics.items() if value is not None)
        status = "通" if result.ok else "失败：" + result.error.replace("\n", " ")[:120]
        lines.append(
            f"| {result.provider} | `{result.adapter}` | {result.mode} | {status} | {metrics or '-'} |"
        )

    lines.append("")
    lines.append("## 明细")
    for result in results:
        lines.append("")
        lines.append(f"### {result.provider}")
        for key, value in result.detail.items():
            if value in (None, ""):
                continue
            lines.append(f"- {key}：{value}")
        if not result.ok:
            lines.append(f"- 错误：{result.error}")

    lines.append("")
    lines.append("## 接口信息（2026-11-22 已核对的公开文档）")
    lines.append("- MiMo ASR：`POST https://api.xiaomimimo.com/v1/chat/completions`，模型 `mimo-v2.5-asr`，`api-key` 或 Bearer；WAV/MP3 走 `input_audio` data URI。")
    lines.append("- MiMo LLM：`https://api.xiaomimimo.com/v1`，模型 `mimo-v2.6-flash` / `mimo-v2.6-pro`；thinking 模式下不要发送 temperature。")
    lines.append("- Breeze TTS：`POST https://api.breeze.blue/v1/text-to-speech/{voice_id}`，`xi-api-key`，`model_id=breeze-tts-2`，`output_format=mp3_24000_128`。")
    lines.append("- DeepSeek Flash：`POST https://api.deepseek.com/v1/chat/completions`，模型 `deepseek-chat`，Bearer 鉴权；2026-11-23 实测 3/3 可解析，平均 979ms。")
    lines.append("")
    lines.append("## 仍缺")
    lines.append("- MiMo API key（LLM 与 ASR 共用）。")
    lines.append("- Breeze API key 与 voice_id（形如 `voc_...`）。")
    lines.append("- 真实语音样本：优先放 WAV/MP3；MiMo 不接受 webm/ogg。")
    lines.append("")
    lines.append("## 下一步")
    lines.append("1. 把 key 写进 `.env`（参照 `.env.example`），`PROVIDER_MODE=real`。")
    lines.append("2. 跑 `python -m bff.probe --mode real --only llm,asr,tts`。")
    lines.append("3. 真实结果确认后，按 `docs/designs/FREEZE.md` 的变更规则更新待定区与新哈希。")
    return "\n".join(lines) + "\n"


def write_report(
    settings: Settings,
    results: list[ProbeResult],
    *,
    out_dir: Path = PROBE_OUT_DIR,
    when: datetime | None = None,
) -> tuple[Path, Path]:
    when = when or datetime.now()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = when.strftime("%Y-%m-%d-%H%M%S")
    md_path = out_dir / f"{stamp}.md"
    json_path = out_dir / f"{stamp}.json"

    md_path.write_text(render_markdown(settings, results, when), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "when": when.isoformat(timespec="seconds"),
                "mode": settings.mode,
                "providers": settings.summary(),
                "results": [dataclasses.asdict(result) for result in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return md_path, json_path


ALL_PROVIDERS = ("llm", "asr", "tts", "scorer")


async def run_probes(
    settings: Settings, repeat: int, only: set[str] | None = None
) -> list[ProbeResult]:
    selected = set(only or ALL_PROVIDERS)
    providers = build_providers(settings, required=selected)
    try:
        results: list[ProbeResult] = []
        if "llm" in selected:
            results.append(await probe_llm(providers))
        if "asr" in selected:
            results.append(await probe_asr(providers, language=settings.asr_language))
        if "tts" in selected:
            results.append(await probe_tts(providers))
        if "scorer" in selected:
            results.append(await probe_scorer(providers, repeat))
        return results
    finally:
        await providers.aclose()


async def _run_or_report_error(
    settings: Settings, repeat: int, only: set[str] | None = None
) -> list[ProbeResult] | None:
    try:
        return await run_probes(settings, repeat, only)
    except ProviderNotConfigured as exc:
        print(f"配置不完整，探针无法启动：{exc}", file=sys.stderr)
        print("补齐 .env 里的地址与密钥，或先用 --mode fake 验证链路。", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="d0a 四 API 连通性探针")
    parser.add_argument("--mode", choices=("auto", "real", "fake"), help="覆盖 PROVIDER_MODE")
    parser.add_argument("--repeat", type=int, default=3, help="评分 JSON 稳定性采样次数")
    parser.add_argument(
        "--only",
        default="llm,asr,tts,scorer",
        help="逗号分隔：llm,asr,tts,scorer（默认全测）",
    )
    parser.add_argument("--out", type=Path, default=PROBE_OUT_DIR, help="报告输出目录")
    parser.add_argument("--no-write", action="store_true", help="只打印，不写文件")
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.mode:
        settings = dataclasses.replace(settings, mode=args.mode)

    only = {part.strip().lower() for part in args.only.split(",") if part.strip()}
    invalid = only - set(ALL_PROVIDERS)
    if not only or invalid:
        parser.error(f"--only 只接受 {','.join(ALL_PROVIDERS)}，收到 {sorted(invalid)}")

    results = asyncio.run(_run_or_report_error(settings, max(1, args.repeat), only))
    if results is None:
        return 2

    for result in results:
        status = "OK " if result.ok else "FAIL"
        print(f"[{status}] {result.provider:14} mode={result.mode:5} {result.metrics}")
        if not result.ok:
            print(f"       {result.error}")

    if not args.no_write:
        md_path, json_path = write_report(settings, results, out_dir=args.out)
        print(f"\n报告：{md_path}")
        print(f"原始：{json_path}")

    if settings.mode == MODE_FAKE:
        print("\n注意：fake 模式没有验证任何真实 API。")
        return 0
    return 0 if all(result.ok for result in results) else 2


if __name__ == "__main__":
    sys.exit(main())
