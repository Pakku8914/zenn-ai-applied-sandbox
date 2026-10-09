"""止め方の部品。

- Drain：SIGTERM を受けてからの「店じまい」の状態。begin() 以降は /ready が 503・新しいストリームは 503 になり、
  配信中のストリームには grace_seconds の猶予を与える（過ぎたら expired が立ち、中継側が error で閉じる）
- StreamGate：1ワーカー（1プロセス）が同時に配信するストリームの数と上限
- install_drain_signals()：uvicorn のシグナルハンドラの前に drain.begin() を挟む

uvicorn は SIGTERM を自分で受け、待ち受けを閉じてから配信中の接続が終わるのを待つ。
ただしアプリには何も知らせない（lifespan の終了処理が呼ばれるのは、接続がすべて終わった後）。
そこで lifespan の起動処理で、uvicorn が入れたハンドラを包んで、止まり始めたことを知る。
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from types import FrameType

logger = logging.getLogger("kondate.session16.lifecycle")


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
    """SIGTERM・SIGINT のハンドラを包み、drain.begin() を先に呼ぶ。戻り値は元に戻す関数。

    lifespan の起動処理（＝uvicorn がハンドラを入れた後・メインスレッド）で呼ぶ。
    まだ誰もハンドラを入れていない（uvicorn の外で動いている）シグナルには手を出さない。
    """
    loop = asyncio.get_running_loop()
    installed: dict[int, Callable[[int, FrameType | None], object]] = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous = signal.getsignal(sig)
        if not callable(previous):
            continue  # SIG_DFL・SIG_IGN：既定の動き（プロセスの終了）を変えない

        def handler(signum: int, frame: FrameType | None, previous=previous) -> None:
            # シグナルハンドラはループの処理の途中に割り込んで動く。ループの操作は「頼む」だけにする
            loop.call_soon_threadsafe(drain.begin)
            previous(signum, frame)  # uvicorn の handle_exit：待ち受けを閉じ、配信中の接続を待つ

        try:
            signal.signal(sig, handler)
        except ValueError:  # メインスレッド以外では入れられない
            logger.warning("drain_signal_unavailable")
            break
        installed[sig] = previous

    def restore() -> None:
        for sig, previous in installed.items():
            signal.signal(sig, previous)

    return restore
