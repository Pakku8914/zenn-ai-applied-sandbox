"""練習問題1の解答：固定窓のカウンタを Lua で作り、窓の境界で上限の2倍が通ることを確かめる。"""

from __future__ import annotations

from datetime import datetime

from redis.asyncio import Redis

from .limiter import epoch_ms

WINDOW_MS = 60_000

FIXED_WINDOW_LUA = """
-- 固定窓。KEYS[1]: その窓のカウンタ  ARGV[1]: 上限  ARGV[2]: キーの寿命（ミリ秒）
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
if count > tonumber(ARGV[1]) then
  return 0
end
return 1
"""


class FixedWindow:
    def __init__(self, redis: Redis, prefix: str = "s10:q1") -> None:
        self.prefix = prefix
        self._script = redis.register_script(FIXED_WINDOW_LUA)

    async def take(self, user_id: str, limit: int, now: datetime) -> bool:
        window = epoch_ms(now) // WINDOW_MS  # 何番目の1分か（毎分 00 秒で次の窓に切り替わる）
        key = f"{self.prefix}:{user_id}:{window}"
        # 寿命は窓2つぶん：窓が終わればもう読まれないので、消えるのが少し遅れても害はない
        return bool(await self._script(keys=[key], args=[limit, WINDOW_MS * 2]))
