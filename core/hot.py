"""热项 CLI：capture | list | discard（Coach 落地前的手动入口）。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .db import connect, init_schema
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.hot")
    default_db = Path(os.environ.get("DB_PATH") or "data/app.db")
    parser.add_argument("--db", type=Path, default=default_db)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", type=Path, default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", parents=[common], help="捕获一条热项")
    capture.add_argument("text", nargs="?", help="热项正文；省略时从 stdin 读取")
    capture.add_argument("--title")
    capture.add_argument("--source-url")
    capture.add_argument("--source-kind", choices=["session", "agent"], default="session")
    capture.add_argument("--origin", choices=["user", "question"], required=True)
    capture.add_argument("--ttl-days", type=int, default=7)

    listing = sub.add_parser("list", parents=[common], help="列出未过期热项")
    listing.add_argument("--limit", type=int, default=20)

    discard = sub.add_parser("discard", parents=[common], help="丢弃一条热项")
    discard.add_argument("hot_id", type=int)

    args = parser.parse_args(argv)
    store = Store(connect(args.db))
    try:
        init_schema(store.conn)
        if args.command == "capture":
            store.expire_hot_items()
            text = args.text if args.text is not None else sys.stdin.read()
            try:
                hot_id = store.capture_hot_item(
                    source_kind=args.source_kind,
                    text=text,
                    text_origin=args.origin,
                    title=args.title,
                    source_url=args.source_url,
                    ttl_days=args.ttl_days,
                )
            except ValueError as exc:
                print(f"捕获失败：{exc}", file=sys.stderr)
                return 1
            print(f"hot={hot_id}")
            return 0

        if args.command == "list":
            store.expire_hot_items()
            items = store.list_hot_items(args.limit)
            if not items:
                print("没有未过期的热项")
                return 0
            for item in items:
                label = item.title or item.text[:40]
                print(
                    f"#{item.id} {item.age_days}d seen={item.seen_count} "
                    f"[{item.source_kind}] {label}"
                )
            return 0

        if args.command == "discard":
            if store.discard_hot_item(args.hot_id):
                print(f"discarded hot={args.hot_id}")
                return 0
            print("未找到可丢弃的 hot 项", file=sys.stderr)
            return 1
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
