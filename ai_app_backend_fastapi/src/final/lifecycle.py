"""止め方の部品（session16/lifecycle.py のコピー）と、締め切りに気づける中継（session16/relay.py の pump）。

- Drain：SIGTERM を受けてからの「店じまい」。begin() 以降は /ready が 503・新しい会話は 503、
  配信中のストリームには grace_seconds の猶予を与え、過ぎたら expired が立つ
- StreamGate：1プロセスが同時に配信するストリームの数と上限
- pumped()：ツールループを別のタスクで読み、「次のイベント」と「drain の締め切り」の早いほうを待つ
  （上流やツールが黙っている間でも、締め切りに気づいて error で閉じられる）
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import AsyncIterator, Callable
from types import FrameType
from typing import TypeVar

import anyio

from .errors import ServiceUnavailable

logger = logging.getLogger("kondate.final.lifecycle")

T = TypeVar("T")
QUEUE_SIZE = 16


class Drain:
    def __init__(self, grace_seconds: float) -> None:
        self.grace_seconds = grace_seconds
        self.started = False
        self.expired = asyncio.Event()
        self._timer: asyncio.TimerHandle | None = None

    def begin(self) -> None:
        if self.started:
            return
        self.started = True
        self._timer = asyncio.get_running_loop().call_later(self.grace_seconds, self.expired.set)
        logger.warning("drain_started", extra={"grace_seconds": self.grace_seconds})

    def cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()


class StreamGate:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.active = 0

    @property
    def full(self) -> bool:
        return self.active >= self.limit

    def try_enter(self) -> bool:
        if self.full:
            return False
        self.active += 1
        return True

    def leave(self) -> None:
        self.active -= 1


def install_drain_signals(drain: Drain) -> Callable[[], None]:
    """SIGTERM・SIGINT のハンドラを包み、drain.begin() を先に呼ぶ（uvicorn の外で動いているときは何もしない）。"""
    loop = asyncio.get_running_loop()
    installed: dict[int, Callable[[int, FrameType | None], object]] = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous = signal.getsignal(sig)
        if not callable(previous):
            continue

        def handler(signum: int, frame: FrameType | None, previous=previous) -> None:
            loop.call_soon_threadsafe(drain.begin)
            previous(signum, frame)

        try:
            signal.signal(sig, handler)
        except ValueError:
            logger.warning("drain_signal_unavailable")
            break
        installed[sig] = previous

    def restore() -> None:
        for sig, previous in installed.items():
            signal.signal(sig, previous)

    return restore


async def _next_item(queue: asyncio.Queue, drain: Drain) -> tuple[str, object] | None:
    if drain.expired.is_set():
        return None
    get = asyncio.ensure_future(queue.get())
    expired = asyncio.ensure_future(drain.expired.wait())
    try:
        await asyncio.wait((get, expired), return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (get, expired):
            if not task.done():
                task.cancel()
    if get.done() and not get.cancelled():
        return get.result()
    return None


async def pumped(source: AsyncIterator[T], drain: Drain) -> AsyncIterator[T]:
    """source を別のタスクで読み、締め切りが来たら ServiceUnavailable を送出する。"""
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue(maxsize=QUEUE_SIZE)

    async def pump() -> None:
        try:
            async for item in source:
                await queue.put(("item", item))
            await queue.put(("end", None))
        except Exception as exc:  # CancelledError（止められた）は BaseException なので、ここには来ない
            await queue.put(("error", exc))

    producer = asyncio.create_task(pump())
    try:
        while True:
            got = await _next_item(queue, drain)
            if got is None:
                raise ServiceUnavailable("drain の締め切りを過ぎた")
            kind, value = got
            if kind == "end":
                return
            if kind == "error":
                assert isinstance(value, Exception)
                raise value
            yield value  # type: ignore[misc]
    finally:
        producer.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(producer, return_exceptions=True)
