"""Redis で数える部品（session13/limiter.py のコピー。キーの接頭辞だけ final に変えた）と、プラン別の上限（plans.py）。

キー：final:rate:<user> / final:quota:<user>:<YYYYMMDD> / final:upstream:until
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from uuid_utils import uuid7

from kondate.clock import JST

PREFIX = "final"
SCALE = 60_000
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
DAY_MS = 86_400_000

# ---------------------------------------------------------------- プラン別の上限（session10/plans.py）


@dataclass(frozen=True)
class PlanLimits:
    requests_per_minute: int
    tokens_per_day: int


class LimitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LIMIT_", extra="ignore")

    free_requests_per_minute: int = Field(default=10, gt=0)
    free_tokens_per_day: int = Field(default=20_000, gt=0)
    pro_requests_per_minute: int = Field(default=60, gt=0)
    pro_tokens_per_day: int = Field(default=200_000, gt=0)
    hold_seconds: int = Field(default=600, gt=0)

    def for_plan(self, plan: str) -> PlanLimits:
        if plan == "free":
            return PlanLimits(self.free_requests_per_minute, self.free_tokens_per_day)
        if plan == "pro":
            return PlanLimits(self.pro_requests_per_minute, self.pro_tokens_per_day)
        raise ValueError(f"未知のプランです: {plan}")


def jst_day(now: datetime) -> str:
    return now.astimezone(JST).strftime("%Y%m%d")


def next_reset(now: datetime) -> datetime:
    today = now.astimezone(JST).date()
    return datetime.combine(today + timedelta(days=1), time(0), tzinfo=JST)


def seconds_until_reset(now: datetime) -> int:
    return max(1, math.ceil((next_reset(now) - now).total_seconds()))


# ---------------------------------------------------------------- Lua（session10 のまま）

TOKEN_BUCKET_LUA = """
local scale = tonumber(ARGV[4])
local capacity = tonumber(ARGV[1]) * scale
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local state = redis.call('HMGET', KEYS[1], 'level', 'ts')
local level = tonumber(state[1]) or capacity
local ts = tonumber(state[2]) or now
if now > ts then
  level = math.min(capacity, level + (now - ts) * rate)
  ts = now
end
local allowed = 0
local wait_ms = 0
if level >= scale then
  level = level - scale
  allowed = 1
else
  wait_ms = math.ceil((scale - level) / rate)
end
redis.call('HSET', KEYS[1], 'level', tostring(level), 'ts', tostring(ts))
redis.call('PEXPIRE', KEYS[1], ARGV[5])
return {allowed, math.floor(level / scale), wait_ms}
"""

RESERVE_LUA = """
local limit = tonumber(ARGV[1])
local amount = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local used = 0
local reserved = 0
local flat = redis.call('HGETALL', KEYS[1])
for i = 1, #flat, 2 do
  local field = flat[i]
  local value = flat[i + 1]
  if field == 'used' then
    used = tonumber(value)
  else
    local held, expires = string.match(value, '^(%d+):(%d+)$')
    if tonumber(expires) <= now then
      redis.call('HDEL', KEYS[1], field)
    else
      reserved = reserved + tonumber(held)
    end
  end
end
if used + reserved + amount > limit then
  return {0, used, reserved}
end
redis.call('HSET', KEYS[1], 'r:' .. ARGV[4], ARGV[2] .. ':' .. ARGV[5])
redis.call('PEXPIRE', KEYS[1], ARGV[6])
return {1, used, reserved + amount}
"""

SETTLE_LUA = """
if redis.call('HDEL', KEYS[1], 'r:' .. ARGV[1]) == 0 then
  return -1
end
return redis.call('HINCRBY', KEYS[1], 'used', ARGV[2])
"""


def epoch_ms(now: datetime) -> int:
    return (now - EPOCH) // timedelta(milliseconds=1)


@dataclass(frozen=True)
class BucketResult:
    allowed: bool
    remaining: int
    retry_after_ms: int


@dataclass(frozen=True)
class Reservation:
    id: str
    key: str
    amount: int


@dataclass(frozen=True)
class QuotaState:
    used: int
    reserved: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used - self.reserved)


@dataclass(frozen=True)
class ReserveResult:
    reservation: Reservation | None
    state: QuotaState


class Limiter:
    def __init__(self, redis: Redis, prefix: str = PREFIX) -> None:
        self.redis = redis
        self.prefix = prefix
        self._bucket = redis.register_script(TOKEN_BUCKET_LUA)
        self._reserve = redis.register_script(RESERVE_LUA)
        self._settle = redis.register_script(SETTLE_LUA)

    def bucket_key(self, user_id: str) -> str:
        return f"{self.prefix}:rate:{user_id}"

    def quota_key(self, user_id: str, now: datetime) -> str:
        return f"{self.prefix}:quota:{user_id}:{jst_day(now)}"

    @property
    def cooldown_key(self) -> str:
        return f"{self.prefix}:upstream:until"

    async def take_request(self, user_id: str, limits: PlanLimits, now: datetime) -> BucketResult:
        rpm = limits.requests_per_minute
        ttl_ms = math.ceil(rpm * SCALE / rpm) + 1000
        allowed, remaining, wait_ms = await self._bucket(
            keys=[self.bucket_key(user_id)], args=[rpm, rpm, epoch_ms(now), SCALE, ttl_ms])
        return BucketResult(bool(allowed), int(remaining), int(wait_ms))

    def quota_ttl_ms(self, now: datetime) -> int:
        return epoch_ms(next_reset(now)) - epoch_ms(now) + DAY_MS

    async def reserve(self, user_id: str, limits: PlanLimits, amount: int, now: datetime,
                      hold_seconds: int) -> ReserveResult:
        rid = str(uuid7())
        key = self.quota_key(user_id, now)
        now_ms = epoch_ms(now)
        ok, used, reserved = await self._reserve(
            keys=[key], args=[limits.tokens_per_day, amount, now_ms, rid, now_ms + hold_seconds * 1000,
                              self.quota_ttl_ms(now)])
        state = QuotaState(int(used), int(reserved), limits.tokens_per_day)
        return ReserveResult(Reservation(rid, key, amount) if ok else None, state)

    async def settle(self, reservation: Reservation, actual_tokens: int) -> int | None:
        used = await self._settle(keys=[reservation.key], args=[reservation.id, max(0, actual_tokens)])
        return None if int(used) < 0 else int(used)

    async def upstream_wait_ms(self, now: datetime) -> int:
        raw = await self.redis.get(self.cooldown_key)
        return 0 if raw is None else max(0, int(raw) - epoch_ms(now))

    async def note_upstream_429(self, retry_after_s: int, now: datetime) -> None:
        until = epoch_ms(now) + retry_after_s * 1000
        await self.redis.set(self.cooldown_key, until, px=retry_after_s * 1000 + 1000)
