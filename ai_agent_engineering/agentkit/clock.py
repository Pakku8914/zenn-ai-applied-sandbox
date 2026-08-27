"""時刻の注入。

`datetime.now()` を直接呼ぶと軌跡が再現しなくなる。教材では必ず時計を注入する。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
DEFAULT_NOW = datetime(2026, 8, 15, 9, 0, 0, tzinfo=JST)


class FixedClock:
    """常に同じ時刻を返す時計。"""

    def __init__(self, now: datetime = DEFAULT_NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def today(self) -> str:
        return self._now.strftime("%Y-%m-%d")


class StepClock:
    """呼ばれるたびに一定時間進む時計（所要時間の演習に使う）。"""

    def __init__(self, start: datetime = DEFAULT_NOW, step_seconds: int = 30) -> None:
        self._now = start
        self._step = timedelta(seconds=step_seconds)

    def now(self) -> datetime:
        current = self._now
        self._now += self._step
        return current

    def today(self) -> str:
        return self._now.strftime("%Y-%m-%d")
