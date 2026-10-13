"""CPU を食う処理の入口（セッション14の gate.py の写し）。同時実行数と待ち行列の長さを決め、あふれたら断る。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import anyio

T = TypeVar("T")


class Busy(Exception):
    def __init__(self, gate: str) -> None:
        super().__init__(gate)
        self.gate = gate


class CpuGate:
    def __init__(self, name: str, concurrency: int, max_waiting: int) -> None:
        self.name, self.concurrency, self.max_waiting = name, concurrency, max_waiting
        self.limiter = anyio.CapacityLimiter(concurrency)
        self.inflight = 0
        self.rejected = 0

    def _admit(self) -> None:
        # 判定と予約の間に await を挟まない
        if self.inflight >= self.concurrency + self.max_waiting:
            self.rejected += 1
            raise Busy(self.name)
        self.inflight += 1

    async def run_sync(self, fn: Callable[..., T], *args: Any) -> T:
        self._admit()
        try:
            return await anyio.to_thread.run_sync(fn, *args, limiter=self.limiter)
        finally:
            self.inflight -= 1

    async def run(self, fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        self._admit()
        try:
            async with self.limiter:
                return await fn(*args, **kwargs)
        finally:
            self.inflight -= 1

    def stats(self) -> dict:
        running = int(self.limiter.borrowed_tokens)
        return {"concurrency": self.concurrency, "max_waiting": self.max_waiting,
                "running": running, "waiting": self.inflight - running, "rejected": self.rejected}
