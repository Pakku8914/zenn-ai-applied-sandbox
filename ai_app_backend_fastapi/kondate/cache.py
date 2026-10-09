"""Redis への非同期接続（redis-py の asyncio クライアント）。"""

from __future__ import annotations

from redis.asyncio import Redis

from kondate.settings import get_settings


def make_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)
