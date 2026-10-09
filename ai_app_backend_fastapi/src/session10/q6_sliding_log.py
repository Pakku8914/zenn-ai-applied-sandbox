"""練習問題6の解答：スライディング窓（ログ方式）をソート済み集合と Lua で作る。"""

from __future__ import annotations

from datetime import datetime

from redis.asyncio import Redis
from uuid_utils import uuid7

from .limiter import BucketResult, epoch_ms

SLIDING_LOG_LUA = """
-- スライディング窓（ログ）。KEYS[1]: 通した要求の時刻を並べたソート済み集合（スコア＝ミリ秒）
-- ARGV[1]: 上限  ARGV[2]: 窓（ミリ秒）  ARGV[3]: いまの時刻（ミリ秒）  ARGV[4]: この要求の ID
-- ARGV[5]: 窓の始まり（いま − 窓）。この時刻ちょうどの記録は窓の外とする
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[5])
local count = redis.call('ZCARD', KEYS[1])
if count < limit then
  redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
  redis.call('PEXPIRE', KEYS[1], ARGV[2])
  return {1, limit - count - 1, 0}
end
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
return {0, 0, tonumber(oldest[2]) + window - now}
"""


class SlidingLog:
    def __init__(self, redis: Redis, prefix: str = "s10:q6") -> None:
        self.prefix = prefix
        self._script = redis.register_script(SLIDING_LOG_LUA)

    async def take(self, user_id: str, limit: int, now: datetime, window_ms: int = 60_000) -> BucketResult:
        now_ms = epoch_ms(now)
        allowed, remaining, wait_ms = await self._script(
            keys=[f"{self.prefix}:{user_id}"], args=[limit, window_ms, now_ms, str(uuid7()), now_ms - window_ms])
        return BucketResult(bool(allowed), int(remaining), int(wait_ms))
