"""本文の Bad の例（検証で「なぜ駄目か」を再現するためだけに置く。アプリからは使わない）。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from redis.asyncio import Redis

from .limiter import SCALE
from .plans import PlanLimits


async def naive_take(redis: Redis, key: str, limits: PlanLimits, now_ms: int,
                     between: Callable[[], Awaitable[object]] | None = None) -> bool:
    """Bad（信頼性）：読む → Python で計算 → 書く。①と③の間に、別の要求が同じ残量を読めてしまう。"""
    capacity = limits.requests_per_minute * SCALE
    raw_level, raw_ts = await redis.hmget(key, "level", "ts")  # ① 読む
    level = int(raw_level) if raw_level is not None else capacity
    ts = int(raw_ts) if raw_ts is not None else now_ms
    level = min(capacity, level + max(0, now_ms - ts) * limits.requests_per_minute)  # ② 計算する
    allowed = level >= SCALE
    if allowed:
        level -= SCALE
    if between is not None:  # 検証用：①と③の間に、別のサーバの要求が割り込んだ状況を作る
        await between()
    await redis.hset(key, mapping={"level": level, "ts": max(ts, now_ms)})  # ③ 書く
    return allowed


def utc_day(now: datetime) -> str:
    """Bad（保守性）：UTC の日付で区切ると、日本の利用者には朝 9:00 にクォータが戻る。"""
    return now.astimezone(timezone.utc).strftime("%Y%m%d")
