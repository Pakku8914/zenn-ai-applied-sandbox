"""止め方の部品（session16/lifecycle.py から Drain と install_drain_signals をコピー。StreamGate は省いた）。"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from types import FrameType

logger = logging.getLogger("kondate.review04.lifecycle")


class Drain:
    def __init__(self, grace_seconds: float) -> None:
        self.grace_seconds = grace_seconds
        self.started = False
        self.expired = asyncio.Event()
        self._timer: asyncio.TimerHandle | None = None

    def begin(self) -> None:
        """店じまいを始める。何度呼んでも1回目だけが効く。イベントループの中から呼ぶ。"""
        if self.started:
            return
        self.started = True
        self._timer = asyncio.get_running_loop().call_later(self.grace_seconds, self.expired.set)
        logger.warning("drain_started", extra={"grace_seconds": self.grace_seconds})

    def cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()


def install_drain_signals(drain: Drain) -> Callable[[], None]:
    """SIGTERM・SIGINT のハンドラを包み、drain.begin() を先に呼ぶ。戻り値は元に戻す関数。"""
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
