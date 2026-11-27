"""索引维护 CLI：重建 FTS、按 content_hash 复用向量、补缺失 embedding。

`--prune` 清理找不到对应 material_chunks 行的孤儿索引行；旧版本块的索引保留。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .db import connect, init_schema
from .embedding import embed_missing
from .paths import portable_path
from .store import Store
from .version import code_version


def _stats(**fields: object) -> dict[str, object]:
    return {**fields, "code_version": code_version()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.reindex")
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("DB_PATH") or "data/app.db"))
    parser.add_argument("--model", default="text-embedding-v4")
    parser.add_argument("--dim", type=int, default=1024)
    parser.add_argument("--fts-only", action="store_true", help="只重建 FTS，不补 embedding")
    parser.add_argument("--prune", action="store_true", help="清理找不到块行的孤儿索引行")
    args = parser.parse_args(argv)

    store = Store(connect(args.db))
    try:
        init_schema(store.conn)
        run_id = store.start_pipeline_run("reindex", portable_path(args.db))
        print(f"pipeline_run_id={run_id}")
        count = store.rebuild_fts()
        pruned_embeddings = 0
        pruned_fts = 0
        if args.prune:
            pruned_embeddings, pruned_fts = store.prune_index_orphans()
            print(f"pruned_embeddings={pruned_embeddings} pruned_fts={pruned_fts}")
        missing = store.missing_embedding_chunks(args.model, args.dim)
        if args.fts_only or not missing:
            store.finish_pipeline_run(
                run_id,
                "succeeded",
                _stats(
                    fts_rows=count,
                    embedded=0,
                    skipped=len(missing),
                    failed=0,
                    pruned_embeddings=pruned_embeddings,
                    pruned_fts=pruned_fts,
                ),
            )
            print(f"fts={count} missing_embeddings={len(missing)}")
            return 0

        try:
            from bff.config import load_settings
            from bff.providers.registry import build_providers

            providers = build_providers(load_settings(), required={"embedding"})
        except Exception as exc:
            store.finish_pipeline_run(
                run_id, "failed", _stats(fts_rows=count), error=str(exc)
            )
            print(f"embedding 未配置：{exc}", file=sys.stderr)
            return 2

        if providers.modes.get("embedding") == "fake":
            store.finish_pipeline_run(
                run_id,
                "succeeded",
                _stats(
                    fts_rows=count,
                    embedded=0,
                    skipped=len(missing),
                    failed=0,
                    pruned_embeddings=pruned_embeddings,
                    pruned_fts=pruned_fts,
                ),
            )
            print(
                f"fts={count} missing_embeddings={len(missing)}；embedding 是 fake，未补",
                file=sys.stderr,
            )
            asyncio.run(providers.aclose())
            return 0

        async def run():
            try:
                return await embed_missing(store, providers.embedder)
            finally:
                await providers.aclose()

        try:
            embedded, failures = asyncio.run(run())
        except Exception as exc:
            store.finish_pipeline_run(
                run_id, "failed", _stats(fts_rows=count), error=str(exc)
            )
            print(f"embedding 补建失败：{exc}", file=sys.stderr)
            return 1
        store.finish_pipeline_run(
            run_id,
            "partial" if failures else "succeeded",
            _stats(
                fts_rows=count,
                embedded=embedded,
                skipped=len(missing) - embedded - len(failures),
                failed=len(failures),
                missing_before=len(missing),
                pruned_embeddings=pruned_embeddings,
                pruned_fts=pruned_fts,
            ),
        )
        print(
            f"fts={count} embedded={embedded} failed={len(failures)} "
            f"missing_before={len(missing)}"
        )
        if failures:
            print("失败的 chunk：" + ", ".join(failures[:5]), file=sys.stderr)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
