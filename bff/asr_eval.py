"""d0 语音验收：20 句术语测试，目标术语逐字包含率 ≥ 80%。

用法（项目根目录）：
    python -m bff.asr_eval              # 按 .env 的 PROVIDER_MODE
    python -m bff.asr_eval --mode real  # 强制真实 ASR

读取 docs/designs/asr-test-set/manifest.md 的表格，逐行找 audio/ 下对应文件；
没有录音的行记为跳过。判定口径见清单与冻结规格：
- 逐字包含，同义替换不算对；英文术语大小写不敏感（ASR 常统一小写）。
- 通过线 80%；fake 模式的结果不构成验收证据。
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.ports import ASRRequest

from .config import MODE_FAKE, PROJECT_ROOT, Settings, load_settings
from .media import mime_for_path
from .providers.base import ProviderNotConfigured
from .providers.registry import Providers, build_providers

TEST_SET_DIR = PROJECT_ROOT / "docs" / "designs" / "asr-test-set"
MANIFEST = TEST_SET_DIR / "manifest.md"
PASS_RATE = 0.8
_TARGET_SEPARATORS = re.compile(r"[、,，]")


@dataclass(frozen=True)
class Row:
    number: str
    text: str
    targets: tuple[str, ...]
    audio: str

    @property
    def audio_path(self) -> Path:
        return TEST_SET_DIR / self.audio

    @property
    def recorded(self) -> bool:
        return bool(self.audio) and self.audio_path.is_file()


@dataclass(frozen=True)
class UtteranceResult:
    row: Row
    transcript: str
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    latency_ms: int

    @property
    def passed(self) -> bool:
        return not self.missing


def parse_manifest(text: str) -> list[Row]:
    """解析清单表格里的数据行；表头与分隔行跳过。"""
    rows: list[Row] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 4:
            continue
        number = cells[0]
        if not number.isdigit():
            continue
        targets = tuple(part.strip() for part in _TARGET_SEPARATORS.split(cells[2]) if part.strip())
        rows.append(Row(number=number, text=cells[1], targets=targets, audio=cells[3]))
    return rows


def _contains(transcript: str, term: str) -> bool:
    return term.lower() in transcript.lower()


async def evaluate(
    providers: Providers,
    rows: list[Row],
    *,
    language: str = "zh",
) -> list[UtteranceResult]:
    results: list[UtteranceResult] = []
    for row in rows:
        if not row.recorded:
            continue
        mime = mime_for_path(row.audio_path) or "audio/wav"
        result = await providers.asr.transcribe(
            ASRRequest(
                audio=row.audio_path.read_bytes(),
                mime=mime,
                sample_rate=16000,
                language=language,
            )
        )
        matched = tuple(term for term in row.targets if _contains(result.text, term))
        missing = tuple(term for term in row.targets if term not in matched)
        results.append(
            UtteranceResult(
                row=row,
                transcript=result.text,
                matched=matched,
                missing=missing,
                latency_ms=result.latency_ms,
            )
        )
    return results


def summarize(results: list[UtteranceResult]) -> dict[str, object]:
    total_terms = sum(len(result.row.targets) for result in results)
    hit_terms = sum(len(result.matched) for result in results)
    rate = hit_terms / total_terms if total_terms else 0.0
    return {
        "utterances": len(results),
        "terms": total_terms,
        "hits": hit_terms,
        "rate": round(rate, 3),
        "passed": rate >= PASS_RATE,
    }


def render_markdown(settings: Settings, results: list[UtteranceResult], when: datetime) -> str:
    summary = summarize(results)
    lines = [
        f"# ASR 术语准确率 — {when:%Y-%m-%d %H:%M}",
        "",
        f"- 模式：`{settings.mode}`（asr={settings.asr.model or '默认'}）",
        f"- 样本：{summary['utterances']} 句 / {summary['terms']} 个目标术语",
        f"- 逐字命中：{summary['hits']}，准确率 **{summary['rate']:.0%}**（门槛 {PASS_RATE:.0%}）",
        f"- 结论：{'通过' if summary['passed'] else '未通过'}",
    ]
    if settings.mode == MODE_FAKE:
        lines.append("")
        lines.append("> 假实现固定返回示例文本，本次结果不构成验收证据。")
    lines += ["", "| # | 目标术语 | 结果 | 缺失 | 转写 |", "|---|---|---|---|---|"]
    for result in results:
        lines.append(
            "| {n} | {targets} | {status} | {missing} | {transcript} |".format(
                n=result.row.number,
                targets="、".join(result.row.targets),
                status="通过" if result.passed else "不过",
                missing="、".join(result.missing) or "-",
                transcript=result.transcript.replace("|", "／") or "（空）",
            )
        )
    return "\n".join(lines) + "\n"


async def _run(settings: Settings) -> tuple[list[UtteranceResult], list[Row]]:
    rows = parse_manifest(MANIFEST.read_text(encoding="utf-8"))
    providers = build_providers(settings)
    try:
        return await evaluate(providers, rows, language=settings.asr_language), rows
    finally:
        await providers.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="d0 ASR 20 句术语准确率")
    parser.add_argument("--mode", choices=("auto", "real", "fake"), help="覆盖 PROVIDER_MODE")
    parser.add_argument("--no-write", action="store_true", help="只打印，不写报告")
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.mode:
        settings = dataclasses.replace(settings, mode=args.mode)

    try:
        results, rows = asyncio.run(_run(settings))
    except ProviderNotConfigured as exc:
        print(f"配置不完整：{exc}", file=sys.stderr)
        return 2

    if not results:
        print(f"还没有录音：把文件放到 {TEST_SET_DIR / 'audio'} 并填好清单。", file=sys.stderr)
        return 2

    summary = summarize(results)
    skipped = len(rows) - len(results)
    for result in results:
        mark = "OK  " if result.passed else "MISS"
        print(f"[{mark}] {result.row.number} {'、'.join(result.row.targets)} -> {result.transcript}")
    print(f"\n准确率 {summary['rate']:.0%}（{summary['hits']}/{summary['terms']}），跳过 {skipped} 句未录音")
    print("通过" if summary["passed"] else f"未通过（门槛 {PASS_RATE:.0%}）")
    if settings.mode == MODE_FAKE:
        print("注意：fake 模式的结果不构成验收证据。")

    if not args.no_write:
        when = datetime.now()
        out = TEST_SET_DIR / f"report-{when:%Y-%m-%d-%H%M%S}.md"
        out.write_text(render_markdown(settings, results, when), encoding="utf-8")
        print(f"报告：{out}")

    if settings.mode == MODE_FAKE:
        return 0
    return 0 if summary["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
