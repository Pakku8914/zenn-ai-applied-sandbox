"""時計の注入。ツール・レート制限・ジョブは datetime.now() を直接呼ばず、Clock を受け取る。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

JST = timezone(timedelta(hours=9), "JST")


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(JST)


class FixedClock:
    """テスト用の止まった時計。advance() で進める。"""

    def __init__(self, at: datetime = datetime(2026, 10, 2, 18, 0, tzinfo=JST)) -> None:
        self._now = at

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
