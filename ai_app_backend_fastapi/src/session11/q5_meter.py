"""練習問題5の解答：経路ごとの応答数を1分単位で数え、直近 N 分のフォールバック率を出す。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from redis.asyncio import Redis

from kondate.clock import JST

from .fallback import Served

KEY_TTL_SECONDS = 7200  # 1分ごとのハッシュは2時間で消える


@dataclass(frozen=True)
class FallbackRatio:
    total: int
    fallback: int
    ratio: float  # fallback / total（小数3桁。total が 0 なら 0.0）
    by_route: dict[str, int]

    def alert(self, threshold: float = 0.2) -> bool:
        return self.total > 0 and self.ratio >= threshold


class FallbackMeter:
    def __init__(self, redis: Redis, prefix: str = "s11:q5") -> None:
        self.redis = redis
        self.prefix = prefix

    def minute_key(self, now: datetime) -> str:
        return f"{self.prefix}:fb:{now.astimezone(JST):%Y%m%d%H%M}"

    async def record(self, served: Served, now: datetime) -> None:
        key = self.minute_key(now)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hincrby(key, served.route, 1)
            pipe.expire(key, KEY_TTL_SECONDS)
            await pipe.execute()

    async def ratio(self, now: datetime, *, minutes: int = 5, primary: str = "primary") -> FallbackRatio:
        by_route: dict[str, int] = {}
        for i in range(minutes):  # いまの1分と、その前の minutes-1 分
            for route, count in (await self.redis.hgetall(self.minute_key(now - timedelta(minutes=i)))).items():
                by_route[route] = by_route.get(route, 0) + int(count)
        total = sum(by_route.values())
        fallback = total - by_route.get(primary, 0)
        return FallbackRatio(total, fallback, round(fallback / total, 3) if total else 0.0, by_route)
