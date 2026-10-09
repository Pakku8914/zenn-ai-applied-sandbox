"""練習問題7：readiness の結果を短い時間だけ共有し、同時に来た確認を1回にまとめる。

ロードバランサやオーケストレーターは、何台もの監視役から数秒ごとに /ready を叩く。
そのたびに DB・Redis に問い合わせると、依存先が弱っているときほど余計な負荷をかける。
- ttl_seconds の間は前回の結果を返す
- 同時に来た確認は、走っている1回の結果を待つ（single-flight）
時計は注入する（テストで時間を進めるため）。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from .probes import ReadinessProbe


class CachedProbe:
    def __init__(self, probe: ReadinessProbe, *, ttl_seconds: float,
                 now: Callable[[], float] = time.monotonic) -> None:
        self.probe = probe
        self.ttl_seconds = ttl_seconds
        self.now = now
        self._result: dict[str, str] | None = None
        self._at = 0.0
        self._running: asyncio.Future[dict[str, str]] | None = None

    async def run(self) -> dict[str, str]:
        if self._result is not None and self.now() - self._at < self.ttl_seconds:
            return self._result
        if self._running is None:
            self._running = asyncio.ensure_future(self._refresh())
        # shield：待っている1人が切断されて取り消されても、ほかの人が待つ確認は止めない
        return await asyncio.shield(self._running)

    async def _refresh(self) -> dict[str, str]:
        try:
            result = await self.probe.run()
            self._result, self._at = result, self.now()
            return result
        finally:
            self._running = None
