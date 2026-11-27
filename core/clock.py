"""可注入的时钟：测试固定今天/现在，生产用本地时间。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def today(self) -> str: ...

    def tomorrow(self) -> str: ...

    def now(self) -> str: ...


class SystemClock:
    def today(self) -> str:
        return date.today().isoformat()

    def tomorrow(self) -> str:
        return (date.today() + timedelta(days=1)).isoformat()

    def now(self) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")
