"""晋升 CLI：把热项写成 materials/inbox/<slug>.md，再走正常 ingest。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .db import connect, init_schema
from .ingestion import material_id
from .models import HotItem
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.promote")
    parser.add_argument("hot_id", type=int)
    parser.add_argument("--inbox", type=Path, default=Path("materials/inbox"))
    parser.add_argument("--slug")
    parser.add_argument(
        "--db", type=Path, default=Path(os.environ.get("DB_PATH") or "data/app.db")
    )
    args = parser.parse_args(argv)

    store = Store(connect(args.db))
    try:
        init_schema(store.conn)
        item = store.hot_item(args.hot_id)
        if item is None or item.status != "hot":
            print("热项不存在或不是 hot 状态", file=sys.stderr)
            return 1

        try:
            args.inbox.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"写入失败：{exc}", file=sys.stderr)
            return 1

        raw = (args.slug or item.title or item.text[:40]).replace("/", " ").replace("\\", " ")
        slug = material_id(args.inbox / f"{raw}.md")
        target = args.inbox / f"{slug}.md"
        content = _render(item)
        if target.exists() and target.read_text(encoding="utf-8") != content:
            target = args.inbox / f"{slug}-{item.content_hash[:8]}.md"
        try:
            _write_atomic(target, content)
        except OSError as exc:
            print(f"写入失败：{exc}", file=sys.stderr)
            return 1

        material = material_id(target)
        if not store.mark_hot_promoted(item.id, material):
            print("热项状态已变化，未晋升", file=sys.stderr)
            return 1

        print(f"{target}  material={material}")
        print(f"下一步：python -m core.ingest {target} --emit-chunks")
        return 0
    finally:
        store.close()


def _render(item: HotItem) -> str:
    lines = ["---"]
    if item.source_url:
        lines.append(f"source_url: {json.dumps(item.source_url, ensure_ascii=False)}")
    lines.append(f"captured_at: {json.dumps(item.captured_at, ensure_ascii=False)}")
    lines.append(f"promoted_from: {json.dumps(f'hot:{item.id}', ensure_ascii=False)}")
    lines.append("---")
    lines.append("")
    lines.append(item.text)
    return "\n".join(lines) + "\n"


def _write_atomic(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


if __name__ == "__main__":
    raise SystemExit(main())
