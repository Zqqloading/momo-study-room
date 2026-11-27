"""候选确认 CLI（KB-25）。

1. 交互两步：质量（正确/抽错/重复）+ 学习决定（要学/已掌握/不学）。
2. 先把确认结果原子写进 `concepts.yaml`（ruamel 保留注释）。
3. 再单事务写 `concepts.status` 与 `concept_sources`。
DB 失败时 YAML 已是真相；用 `--reapply` 重放状态。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ruamel.yaml import YAML

from .concepts import ConceptsError, load_concepts
from .db import connect, init_schema
from .models import ConceptState
from .paths import portable_path
from .store import Store
from .version import code_version

QUALITY = {"c": "correct", "w": "wrong", "d": "duplicate", "p": "pending"}
DECISION = {"l": "learn", "k": "known", "s": "skip", "p": "pending"}
STATUS = {"learn": "active", "known": "known", "skip": "skipped"}


class ConfirmError(RuntimeError):
    """YAML 或候选状态无法安全写入。"""


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.confirm")
    parser.add_argument("candidates", help="core.extract 产出的 candidates.json")
    parser.add_argument("--concepts", type=Path, default=Path("concepts.yaml"))
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("DB_PATH") or "data/app.db"),
    )
    parser.add_argument("--reapply", action="store_true", help="只重放状态，不询问、不写 YAML")
    args = parser.parse_args(argv)

    try:
        data = _load_candidates(args.candidates)
    except (OSError, ValueError, TypeError) as exc:
        print(f"读取 candidates 失败：{exc}", file=sys.stderr)
        return 1

    if not args.reapply:
        _review(data["candidates"], input_fn)
        try:
            _write_candidates(args.candidates, data)
        except OSError as exc:
            message = f"确认结果写回 candidates 失败：{exc}"
            print(message, file=sys.stderr)
            _record_failure(args.db, args.candidates, message)
            return 1

        problems = _validate_sources(args.db, data["candidates"])
        if problems:
            _report_validation_failure(args, problems)
            return 1

        try:
            added = _write_yaml(args.concepts, data["candidates"])
        except ConfirmError as exc:
            message = f"YAML 未写入：{exc}"
            print(message, file=sys.stderr)
            _record_failure(args.db, args.candidates, message)
            return 1
        print(f"YAML 已写入：{len(added)} 个新概念")
    else:
        problems = _validate_sources(args.db, data["candidates"])
        if problems:
            _report_validation_failure(args, problems)
            return 1

    return _apply(args, data)


def _report_validation_failure(args: argparse.Namespace, problems: list[str]) -> None:
    message = "出处校验失败：" + "；".join(problems)
    print(message, file=sys.stderr)
    _record_failure(args.db, args.candidates, message)


def _record_failure(db_path: Path, candidates: str | Path, error: str) -> None:
    store = Store(connect(db_path))
    try:
        init_schema(store.conn)
        run_id = store.start_pipeline_run("confirm", portable_path(candidates))
        store.finish_pipeline_run(run_id, "failed", error=error)
    finally:
        store.close()


def _validate_sources(
    db_path: Path, candidates: list[dict[str, Any]]
) -> list[str]:
    selected = _selected(candidates)
    problems = [
        f"{candidate['id']} 缺少 chunk_id"
        for candidate in selected
        if not candidate.get("chunk_id")
    ]
    chunk_ids = [
        str(candidate["chunk_id"])
        for candidate in selected
        if candidate.get("chunk_id")
    ]
    if not chunk_ids:
        return problems
    store = Store(connect(db_path))
    try:
        init_schema(store.conn)
        missing = store.missing_chunk_ids(chunk_ids)
    finally:
        store.close()
    return problems + [f"{chunk_id} 不存在" for chunk_id in missing]


def _load_candidates(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        raise ValueError("candidates 文件缺少 candidates 数组")
    return data


def _review(candidates: list[dict[str, Any]], input_fn: Callable[[str], str]) -> None:
    for candidate in candidates:
        flags = ", ".join(candidate.get("flags", [])) or "-"
        print(
            f"\n[{candidate.get('id')}] {candidate.get('name')}\n"
            f"  定义：{candidate.get('plain_def')}\n"
            f"  摘录：{candidate.get('source_excerpt')}\n"
            f"  flags：{flags}"
        )
        quality_raw = input_fn("质量 [c]正确/[w]抽错/[d]重复/[p]跳过: ").strip().lower() or "p"
        quality = QUALITY.get(quality_raw, "pending")
        decision = None
        reason = None
        if quality in {"wrong", "duplicate"}:
            reason = input_fn("原因（可空）: ").strip() or None
        elif quality == "correct":
            decision_raw = (
                input_fn("决定 [l]要学/[k]已掌握/[s]不学/[p]暂不: ").strip().lower() or "p"
            )
            decision = DECISION.get(decision_raw)
            if decision == "pending":
                decision = None
        candidate["review"] = {
            "quality": quality,
            "decision": decision,
            "reason": reason,
            "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        }


def _selected(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        candidate
        for candidate in candidates
        if candidate.get("review", {}).get("quality") == "correct"
        and candidate.get("review", {}).get("decision") in STATUS
    ]


def _write_yaml(path: Path, candidates: list[dict[str, Any]]) -> tuple[str, ...]:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 1000
    yaml.allow_unicode = True

    if path.exists():
        try:
            load_concepts(path)
        except ConceptsError as exc:
            raise ConfirmError(f"现有 concepts.yaml 不合规：{exc}") from exc
        data = yaml.load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ConfirmError("concepts.yaml 顶层必须是对象")
    else:
        data = {"version": 1, "concepts": []}

    concepts = data.get("concepts")
    if not isinstance(concepts, list):
        raise ConfirmError("concepts.yaml 缺少 concepts 列表")

    existing_ids = {
        str(item.get("id"))
        for item in concepts
        if isinstance(item, dict) and item.get("id")
    }
    existing_names = {
        str(item.get("name"))
        for item in concepts
        if isinstance(item, dict) and item.get("name")
    }
    selected = _selected(candidates)
    selected_ids = {str(candidate["id"]) for candidate in selected}

    added: list[str] = []
    for candidate in selected:
        concept_id = str(candidate["id"])
        name = str(candidate["name"])
        if concept_id in existing_ids or name in existing_names:
            print(f"跳过 {name}：concepts.yaml 已存在", file=sys.stderr)
            continue

        prerequisites = [
            str(item)
            for item in candidate.get("prerequisites", [])
            if str(item) in existing_ids or str(item) in selected_ids
        ]
        dropped = [
            str(item)
            for item in candidate.get("prerequisites", [])
            if str(item) not in prerequisites
        ]
        if dropped:
            print(f"{name} 丢弃未确认的前置：{', '.join(dropped)}", file=sys.stderr)

        concepts.append(
            {
                "id": concept_id,
                "name": name,
                "aliases": list(candidate.get("aliases", [])),
                "plain_def": candidate["plain_def"],
                "difficulty": int(candidate["difficulty"]),
                "prerequisites": prerequisites,
                "source": {
                    "material": candidate.get("material_path") or "",
                    "url": candidate.get("source_url")
                    or f"local://{candidate.get('material_path', '')}",
                    "excerpt": candidate["source_excerpt"],
                },
            }
        )
        existing_ids.add(concept_id)
        existing_names.add(name)
        added.append(concept_id)

    if not added:
        return ()

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())

    try:
        load_concepts(tmp)
    except ConceptsError as exc:
        tmp.unlink(missing_ok=True)
        raise ConfirmError(f"新 concepts.yaml 校验失败：{exc}") from exc

    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    os.replace(tmp, path)
    return tuple(added)


def _write_candidates(path: str | Path, data: dict[str, Any]) -> None:
    target = Path(path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _apply(args, data: dict[str, Any]) -> int:
    selected = _selected(data["candidates"])
    if not selected:
        print("没有需要应用的状态")
        return 0

    yaml_ids: set[str] = set()
    if args.concepts.exists():
        try:
            yaml_ids = {concept.id for concept in load_concepts(args.concepts)}
        except ConceptsError as exc:
            print(f"concepts.yaml 不合规：{exc}", file=sys.stderr)
            return 1

    targets = [candidate for candidate in selected if str(candidate["id"]) in yaml_ids]
    if not targets:
        print("没有已写入 YAML 的概念需要更新状态")
        return 0

    store = Store(connect(args.db))
    try:
        init_schema(store.conn)
        run_id = store.start_pipeline_run("confirm", portable_path(args.candidates))
        try:
            with store.transaction():
                missing = store.missing_chunk_ids(
                    [
                        str(candidate["chunk_id"])
                        for candidate in targets
                        if candidate.get("chunk_id")
                    ]
                )
                if missing:
                    raise ConfirmError(f"出处块不存在：{', '.join(missing)}")
                for candidate in targets:
                    concept_id = str(candidate["id"])
                    decision = candidate["review"]["decision"]
                    current = store.concept_state(concept_id)
                    mastery = 5 if decision == "known" else (current.mastery if current else 0)
                    state = (
                        replace(current, status=STATUS[decision], prior_status=None, mastery=mastery)
                        if current
                        else ConceptState(id=concept_id, status=STATUS[decision], mastery=mastery)
                    )
                    store.upsert_concept(state)

                    chunk_id = candidate.get("chunk_id")
                    if chunk_id:
                        store.upsert_concept_source(
                            concept_id=concept_id,
                            chunk_id=str(chunk_id),
                            excerpt=str(candidate["source_excerpt"]),
                        )
        except Exception as exc:
            store.finish_pipeline_run(run_id, "failed", error=str(exc))
            print(
                f"状态写入失败：{exc}\nYAML 已写入；用 --reapply 重放状态",
                file=sys.stderr,
            )
            return 1

        counts = {"active": 0, "known": 0, "skipped": 0}
        for candidate in targets:
            counts[STATUS[candidate["review"]["decision"]]] += 1
        store.finish_pipeline_run(
            run_id,
            "succeeded",
            {
                "candidates": len(data["candidates"]),
                "active": counts["active"],
                "known": counts["known"],
                "skipped": counts["skipped"],
                "replayed": int(args.reapply),
                "code_version": code_version(),
            },
        )
        print(f"状态已写入：{len(targets)} 个概念")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
