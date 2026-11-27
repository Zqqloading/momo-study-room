"""路径归一化：`pipeline_runs.input` 只存相对路径。"""

from __future__ import annotations

from pathlib import Path


def portable_path(path: str | Path) -> str:
    """返回相对当前目录的 POSIX 路径；不在当前目录下时只保留文件名。"""
    target = Path(path)
    try:
        return target.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except (OSError, ValueError):
        return target.name
