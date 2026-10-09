"""練習問題3の解答：ブレーカの状態を「読むだけ」で返す（ヘルスチェックや管理画面向け）。"""

from __future__ import annotations

import math
from datetime import datetime

from .breaker import CircuitBreaker, epoch_ms


async def breaker_status(breaker: CircuitBreaker, now: datetime) -> dict:
    """{route, state, failures, retry_in}。retry_in は open のとき、試しの1回が通るまでの秒（切り上げ）。

    allow() を呼ばない：allow() は open → half_open へ進め、試しの1回の権利を使ってしまう。
    """
    h = await breaker.redis.hgetall(breaker.key)
    state = h.get("state", "closed")
    retry_in = 0
    if state == "open":
        reopen_ms = int(h["opened_at"]) + round(breaker.config.open_seconds * 1000)
        retry_in = max(0, math.ceil((reopen_ms - epoch_ms(now)) / 1000))
    return {"route": breaker.name, "state": state, "failures": int(h.get("failures", 0)), "retry_in": retry_in}
