"""入库 CLI：解析 + 切块，写 materials/material_chunks。

- 材料身份：同 path → 同材料；内容哈希变了 version+1，旧块保留。
- 文件改名且内容不变：按 content_hash 认作同一材料，只更新 path/title。
- 只写内容表；FTS 与向量索引由 `python -m core.reindex` 单独建。
- 默认写 data/app.db；`DB_PATH` 或 `--db` 可覆盖。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .db import connect, init_schema
from .ingestion import (
    Chunk,
    IngestError,
    ParsedMaterial,
    chunk_material,
    material_id,
    parse_material,
)
from .paths import portable_path
from .store import Store
from .version import code_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.ingest")
    parser.add_argument("path", help="materials/*.md 或 *.html")
    parser.add_argument("--dry-run", action="store_true", help="只输出 JSON，不写 DB")
    parser.add_argument("--emit-chunks", action="store_true", help="正式入库时同时输出 chunks.json")
    parser.add_argument("--out", type=Path, help="chunks.json 输出路径")
    parser.add_argument("--db", type=Path, help="默认 data/app.db 或 $DB_PATH")
    args = parser.parse_args(argv)

    if args.dry_run:
        try:
            material = parse_material(args.path)
        except IngestError as exc:
            print(f"摄取失败：{exc}", file=sys.stderr)
            return 1
        chunks = chunk_material(material)
        out = args.out or _default_chunks_path()
        _write_json(out, material, chunks)
        _print_chunks(out, chunks)
        return 0

    db_path = args.db or Path(os.environ.get("DB_PATH") or "data/app.db")
    store = Store(connect(db_path))
    try:
        init_schema(store.conn)
        run_id = store.start_pipeline_run("ingest", portable_path(args.path))
        print(f"pipeline_run_id={run_id}")
        try:
            material = parse_material(args.path)
        except IngestError as exc:
            store.finish_pipeline_run(run_id, "failed", error=str(exc))
            print(f"摄取失败：{exc}", file=sys.stderr)
            return 1

        try:
            return _ingest(store, args, material, run_id, db_path)
        except Exception as exc:
            store.finish_pipeline_run(
                run_id, "failed", error=f"{type(exc).__name__}: {exc}"
            )
            raise
    finally:
        store.close()


def _ingest(
    store: Store,
    args: argparse.Namespace,
    material: ParsedMaterial,
    run_id: int,
    db_path: Path,
) -> int:
    content_hash = _file_hash(Path(args.path))
    existing = store.material_by_path(material.path)
    if existing is None:
        by_hash = store.material_by_hash(content_hash)
        if by_hash is not None and not Path(by_hash["path"]).exists():
            version = int(by_hash["version"])
            with store.transaction():
                store.upsert_material(
                    material_id=by_hash["id"],
                    title=material.title,
                    path=material.path,
                    format=material.format,
                    content_hash=content_hash,
                    version=version,
                    added_at=by_hash["added_at"],
                    status="active",
                    source_url=_source_url(material),
                    tags_json=_tags_json(material),
                )
            ok = _emit_and_finish(
                store,
                run_id,
                args,
                material,
                version,
                _stats(materials=1),
                mid=by_hash["id"],
            )
            print(f"{material.path} renamed (id={by_hash['id']})")
            return 0 if ok else 1
        existing = store.material_by_id(material_id(material.path))

    if existing is not None and existing["content_hash"] == content_hash:
        version = int(existing["version"])
        ok = _emit_and_finish(
            store,
            run_id,
            args,
            material,
            version,
            _stats(skipped_unchanged=1),
            mid=str(existing["id"]),
        )
        print(f"{material.path} unchanged (v{version})")
        return 0 if ok else 1

    version = 1 if existing is None else int(existing["version"]) + 1
    target_id = existing["id"] if existing is not None else material_id(material.path)
    chunks = chunk_material(material, version=version, mid=target_id)
    added_at = datetime.now().isoformat(timespec="seconds")
    with store.transaction():
        store.upsert_material(
            material_id=target_id,
            title=material.title,
            path=material.path,
            format=material.format,
            content_hash=content_hash,
            version=version,
            added_at=added_at,
            status="active",
            source_url=_source_url(material),
            tags_json=_tags_json(material),
        )
        store.insert_chunks([chunk.to_dict() for chunk in chunks])

    parents = sum(1 for chunk in chunks if chunk.level == "parent")
    ok = _emit_and_finish(
        store,
        run_id,
        args,
        material,
        version,
        _stats(parents=parents, children=len(chunks) - parents, materials=1),
        mid=target_id,
    )
    print(
        f"{db_path}  material={target_id} v{version} "
        f"parent={parents} child={len(chunks) - parents}"
    )
    print("chunks written; run `python -m core.reindex` for FTS/embedding")
    return 0 if ok else 1


def _default_chunks_path() -> Path:
    return Path("data/candidates") / f"{datetime.now():%Y%m%d-%H%M%S}.chunks.json"


def _print_chunks(out: Path, chunks: tuple[Chunk, ...]) -> None:
    parents = sum(1 for chunk in chunks if chunk.level == "parent")
    print(f"{out}  parent={parents} child={len(chunks) - parents}")


def _stats(
    *,
    parents: int = 0,
    children: int = 0,
    materials: int = 0,
    skipped_unchanged: int = 0,
    failed: int = 0,
) -> dict[str, object]:
    return {
        "files": 1,
        "materials": materials,
        "chunks_parent": parents,
        "chunks_child": children,
        "skipped_unchanged": skipped_unchanged,
        "failed": failed,
        "code_version": code_version(),
    }


def _emit_and_finish(
    store: Store,
    run_id: int,
    args: argparse.Namespace,
    material: ParsedMaterial,
    version: int,
    stats: dict[str, object],
    *,
    mid: str | None = None,
) -> bool:
    """按需输出 chunks.json，并收尾 pipeline run；输出失败记为 partial。"""
    error = None
    if args.emit_chunks:
        out = args.out or _default_chunks_path()
        try:
            _write_json(out, material, chunk_material(material, version=version, mid=mid))
            print(f"chunks: {out} v{version}")
        except OSError as exc:
            error = f"emit chunks failed: {exc}"
    store.finish_pipeline_run(
        run_id, "partial" if error else "succeeded", stats, error=error
    )
    if error:
        print(error, file=sys.stderr)
    return error is None


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_url(material: ParsedMaterial) -> str:
    return material.source_url or f"local://{material.path}"


def _tags_json(material: ParsedMaterial) -> str | None:
    return json.dumps(list(material.tags), ensure_ascii=False) if material.tags else None


def _write_json(path: Path, material: ParsedMaterial, chunks: tuple[Chunk, ...]) -> None:
    payload = {
        "material": {
            "path": material.path,
            "title": material.title,
            "format": material.format,
            "source_url": material.source_url,
            "tags": list(material.tags),
        },
        "chunks": [chunk.to_dict() for chunk in chunks],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
