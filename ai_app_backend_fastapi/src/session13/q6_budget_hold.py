"""練習問題6の解答：予算の「保留」を Redis で原子的に取り、同時に来た要求が2つとも予算をすり抜けないようにする。

金額は 1e-8 USD を1単位にした整数で渡す（Lua の数は倍精度なので、小数の USD を渡すと誤差が出る）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from redis.asyncio import Redis
from uuid_utils import uuid7

from kondate.clock import JST

from .budget import BudgetState
from .limiter import DAY_MS, epoch_ms

HOLD_LUA = """
-- KEYS[1]: その月の保留  ARGV[1]: 予算  ARGV[2]: 台帳の今月の使用額  ARGV[3]: 今回の見積もり（いずれも単位）
-- ARGV[4]: いまの時刻（ミリ秒）  ARGV[5]: 保留ID  ARGV[6]: 保留の期限（ミリ秒）  ARGV[7]: キーの寿命（ミリ秒）
local held = 0
local flat = redis.call('HGETALL', KEYS[1])
for i = 1, #flat, 2 do
  local amount, expires = string.match(flat[i + 1], '^(%d+):(%d+)$')
  if tonumber(expires) <= tonumber(ARGV[4]) then
    redis.call('HDEL', KEYS[1], flat[i])
  else
    held = held + tonumber(amount)
  end
end
if tonumber(ARGV[2]) + held + tonumber(ARGV[3]) > tonumber(ARGV[1]) then
  return 0
end
redis.call('HSET', KEYS[1], ARGV[5], ARGV[3] .. ':' .. ARGV[6])
redis.call('PEXPIRE', KEYS[1], ARGV[7])
return 1
"""


def to_units(amount: Decimal) -> int:
    """USD を 1e-8 USD 単位の整数にする。小数8桁を超える端数があれば断る（黙って切り捨てない）。"""
    units = amount.scaleb(8)
    if units != units.to_integral_value():
        raise ValueError(f"小数8桁を超える金額です: {amount}")
    return int(units)


@dataclass(frozen=True)
class Hold:
    id: str
    key: str  # 月が替わってから解放しても、保留した月のキーを消せるように持っておく


class BudgetHold:
    def __init__(self, redis: Redis, prefix: str = "s13:q6") -> None:
        self.redis = redis
        self.prefix = prefix
        self._hold = redis.register_script(HOLD_LUA)

    def key(self, user_id: str, now: datetime) -> str:
        return f"{self.prefix}:budget:{user_id}:{now.astimezone(JST):%Y%m}"

    async def hold(self, user_id: str, state: BudgetState, now: datetime, hold_seconds: int = 600) -> Hold | None:
        """台帳の使用額＋期限内の保留＋今回の見積もりが予算に収まるなら保留する。収まらなければ None。"""
        hold = Hold(str(uuid7()), self.key(user_id, now))
        now_ms = epoch_ms(now)
        ok = await self._hold(keys=[hold.key], args=[
            to_units(state.limit_usd), to_units(state.spent_usd), to_units(state.estimate_usd),
            now_ms, hold.id, now_ms + hold_seconds * 1000, 40 * DAY_MS])
        return hold if ok else None

    async def release(self, hold: Hold) -> bool:
        """台帳に記録し終えたら解放する（使った額は台帳の使用額に入ったので、二重に数えない）。"""
        return bool(await self.redis.hdel(hold.key, hold.id))
