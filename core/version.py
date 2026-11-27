"""代码版本标记：写入 `pipeline_runs`，供 L1 重放判断当时的解析器版本。"""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_VERSION_FILE = _ROOT / "VERSION"


def _read_version() -> str:
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def app_version() -> str:
    """发布版本号：读 `VERSION` 文件，缺失时返回 `0.0.0`。"""
    return _read_version() or "0.0.0"


def code_version() -> str | None:
    """返回 `<short-sha>[-dirty]`；非 git 检出（如容器）退回 `VERSION`，都取不到时返回 None。"""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if head.returncode != 0:
            return _read_version() or None
        sha = head.stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else False
        return f"{sha}-dirty" if dirty else sha
    except (OSError, subprocess.SubprocessError):
        return _read_version() or None
