"""抽取 CLI：chunks.json → candidates.json（DeepSeek / JsonScorer）。

CLI 是组装根：这里才 import bff 的 provider 装配；`core.extraction` 只依赖
`JsonScorer` 协议，不碰 httpx。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .concepts import ConceptsError, load_concepts
from .db import connect, init_schema
from .extraction import ExistingConcept, Extractor
from .ingestion import Chunk
from .paths import portable_path
from .store import Store
from .version import code_version


def _stats(**fields: object) -> dict[str, object]:
    return {**fields, "code_version": code_version()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.extract")
    parser.add_argument("chunks_json", help="core.ingest --emit-chunks 产出的 chunks.json")
    parser.add_argument("--concepts", type=Path, default=Path("concepts.yaml"))
    parser.add_argument("--out", type=Path, help="默认 data/candidates/<时间>.candidates.json")
    parser.add_argument("--limit", type=int, help="只跑前 N 个父块（调试用）")
    parser.add_argument(
        "--db", type=Path, default=Path(os.environ.get("DB_PATH") or "data/app.db")
    )
    args = parser.parse_args(argv)

    store = Store(connect(args.db))
    try:
        init_schema(store.conn)
        run_id = store.start_pipeline_run("extract", portable_path(args.chunks_json))
        print(f"pipeline_run_id={run_id}")

        try:
            material, chunks = _load_chunks(args.chunks_json)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            store.finish_pipeline_run(run_id, "failed", error=str(exc))
            print(f"读取 chunks.json 失败：{exc}", file=sys.stderr)
            return 1

        try:
            existing = _load_existing(args.concepts)
        except ConceptsError as exc:
            store.finish_pipeline_run(run_id, "failed", error=str(exc))
            print(f"concepts.yaml 不合规：{exc}", file=sys.stderr)
            return 1

        parents = [chunk for chunk in chunks if chunk.level == "parent"]
        if args.limit is not None:
            parents = parents[: args.limit]
        if not parents:
            store.finish_pipeline_run(run_id, "failed", error="没有父块可抽取")
            print("没有父块可抽取", file=sys.stderr)
            return 1

        source_url = source_url_for(material, args.chunks_json)

        from bff.config import load_settings
        from bff.providers.base import ProviderError, ProviderNotConfigured
        from bff.providers.registry import build_providers

        try:
            providers = build_providers(load_settings(), required={"scorer"})
        except ProviderNotConfigured as exc:
            store.finish_pipeline_run(run_id, "failed", error=str(exc))
            print(f"抽取需要真实的 scorer：{exc}", file=sys.stderr)
            return 2
        if providers.modes.get("scorer") == "fake":
            store.finish_pipeline_run(run_id, "failed", error="scorer 是 fake")
            print("scorer 未配置；抽取需要 DeepSeek，不拿 FakeScorer 冒充", file=sys.stderr)
            return 2

        async def run():
            try:
                return await Extractor(providers.scorer).extract(
                    parents,
                    source_url=source_url,
                    material_path=str(material.get("path", args.chunks_json)),
                    existing=existing,
                )
            finally:
                await providers.aclose()

        try:
            report = asyncio.run(run())
        except ProviderError as exc:
            store.finish_pipeline_run(run_id, "failed", error=str(exc))
            print(f"抽取失败：{exc}", file=sys.stderr)
            return 1

        payload = {
            "material": material,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "candidates": [candidate.to_dict() for candidate in report.candidates],
            "warnings": list(report.warnings),
            "failures": [failure.to_dict() for failure in report.failures],
        }
        out = args.out or Path("data/candidates") / f"{datetime.now():%Y%m%d-%H%M%S}.candidates.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        store.finish_pipeline_run(
            run_id,
            "partial" if report.failures else "succeeded",
            _stats(
                parents=len(parents),
                candidates=len(report.candidates),
                passed=sum(1 for candidate in report.candidates if not candidate.flags),
                flagged=sum(1 for candidate in report.candidates if candidate.flags),
                discarded=report.discarded,
                warnings=len(report.warnings),
                failed=len(report.failures),
            ),
        )
        print(
            f"{out}  candidates={len(report.candidates)} "
            f"warnings={len(report.warnings)} failures={len(report.failures)}"
        )
        return 0
    finally:
        store.close()


def source_url_for(material: dict[str, object], fallback_path: str | Path) -> str:
    url = material.get("source_url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    return f"local://{material.get('path') or fallback_path}"


def _load_chunks(path: str | Path) -> tuple[dict[str, object], list[Chunk]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    material = data["material"]
    chunks = [
        Chunk(**{**item, "flags": tuple(item.get("flags", []))})
        for item in data["chunks"]
    ]
    return material, chunks


def _load_existing(path: Path) -> list[ExistingConcept]:
    if not path.exists():
        return []
    return [
        ExistingConcept(id=concept.id, name=concept.name, aliases=concept.aliases)
        for concept in load_concepts(path)
    ]


if __name__ == "__main__":
    raise SystemExit(main())
