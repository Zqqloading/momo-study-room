from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_vad_pure_functions_with_synthetic_pcm() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node 不可用，跳过浏览器 VAD 纯函数测试")

    result = subprocess.run(
        [node, "--test", "tests/vad.test.mjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
