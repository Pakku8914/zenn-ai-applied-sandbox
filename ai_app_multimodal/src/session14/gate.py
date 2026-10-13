"""CPU を食う処理の入口：同時実行数と待ち行列の長さを決め、あふれたら待たせずに断る。

    gate = CpuGate("stt", concurrency=1, max_waiting=2)
    res = await gate.run_sync(stt.transcribe, audio, 16000)          # 同期関数をスレッドで動かす
    res = await gate.run(vv.synthesize, text, sample_rate=24000)     # async 関数（CPU は別のコンテナ）

「動いている数＋待っている数」が concurrency＋max_waiting に達していたら Busy を上げる。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import anyio

T = TypeVar("T")


class Busy(Exception):
    """待ち行列があふれた。どの入口か（stt / tts）だけを持つ。"""

    def __init__(self, gate: str) -> None:
        super().__init__(gate)
        self.gate = gate


class CpuGate:
    def __init__(self, name: str, concurrency: int, max_waiting: int) -> None:
        self.name, self.concurrency, self.max_waiting = name, concurrency, max_waiting
        self.limiter = anyio.CapacityLimiter(concurrency)  # 同時に動かす数
        self.inflight = 0      # 受け付けた数（動いている＋待っている）
        self.rejected = 0      # あふれて断った数（起動してからの累計）

    def _admit(self) -> None:
        # 判定と予約（inflight を増やす）の間に await を挟まない。挟むと、同時に来た要求が全員「空いている」と判定してしまう
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
