"""練習問題5の解答：上流の待ち時間をモデルごとに持ち、短い retry-after で縮めない。"""

from __future__ import annotations

from datetime import datetime

from redis.asyncio import Redis

from .limiter import epoch_ms

COOLDOWN_MAX_LUA = """
-- 上流の待ち時間を「遅い方の期限」に合わせる
-- KEYS[1]: 待ち時間のキー  ARGV[1]: 新しい期限（ミリ秒）  ARGV[2]: キーの寿命（ミリ秒）
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local proposed = tonumber(ARGV[1])
if proposed > current then
  redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2])
  return proposed
end
return current
"""


class ModelCooldown:
    def __init__(self, redis: Redis, prefix: str = "s10:q5") -> None:
        self.redis = redis
        self.prefix = prefix
        self._script = redis.register_script(COOLDOWN_MAX_LUA)

    def key(self, model: str) -> str:
        return f"{self.prefix}:upstream:{model}:until"

    async def note_429(self, model: str, retry_after_s: int, now: datetime) -> int:
        """上流の 429 を記録し、待ち終わる時刻（UNIX ミリ秒）を返す。"""
        until = epoch_ms(now) + retry_after_s * 1000
        return int(await self._script(keys=[self.key(model)], args=[until, retry_after_s * 1000 + 1000]))

    async def wait_ms(self, model: str, now: datetime) -> int:
        raw = await self.redis.get(self.key(model))
        return 0 if raw is None else max(0, int(raw) - epoch_ms(now))
