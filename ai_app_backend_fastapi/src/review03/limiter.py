"""Redis で数える部品：レート制限（トークンバケット）・クォータ（予約と精算）・上流の 429 の待ち時間。

session10/limiter.py のコピー。キーは review03: で始める
（review03:rate:<user> / review03:quota:<user>:<YYYYMMDD> / review03:upstream:until）。
- 判定と更新は Lua スクリプトの中で1回にまとめる（読んでから書くまでの間に、別の要求を割り込ませない）
- 時刻はすべてアプリの Clock から引数で渡す。Lua の中で TIME を呼ばない（FixedClock で試験できるように）
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from uuid_utils import uuid7

from .plans import PlanLimits, jst_day, next_reset

PREFIX = "review03"
SCALE = 60_000  # 1回の要求 = 60,000 単位。1分（60,000 ミリ秒）で rpm 回ぶん戻るので、残量を整数のまま扱える
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
DAY_MS = 86_400_000

TOKEN_BUCKET_LUA = """
-- トークンバケット。残量 level は「1回 = SCALE 単位」の整数。1ミリ秒ごとに rpm 単位ずつ戻る
-- KEYS[1]: バケット
-- ARGV[1]: 容量（回） ARGV[2]: 1分あたりの回数 ARGV[3]: いまの時刻（ミリ秒。アプリの Clock）
-- ARGV[4]: SCALE ARGV[5]: キーの寿命（ミリ秒）
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
-- クォータの予約。1日ぶんを1つのハッシュに持つ：used（精算済み）と r:<予約ID>（"予約量:期限ミリ秒"）
-- KEYS[1]: その日のクォータ
-- ARGV[1]: 1日の上限 ARGV[2]: 予約量 ARGV[3]: いまの時刻（ミリ秒） ARGV[4]: 予約ID
-- ARGV[5]: 予約の期限（ミリ秒） ARGV[6]: キーの寿命（ミリ秒）
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
-- 精算。予約を消し、実際に使った量を used に足す。予約が無ければ何もしない（二重の精算・期限切れ）
-- KEYS[1]: 予約した日のクォータ  ARGV[1]: 予約ID  ARGV[2]: 実際に使ったトークン
if redis.call('HDEL', KEYS[1], 'r:' .. ARGV[1]) == 0 then
  return -1
end
return redis.call('HINCRBY', KEYS[1], 'used', ARGV[2])
"""


def epoch_ms(now: datetime) -> int:
    """Clock の時刻を UNIX ミリ秒の整数にする（浮動小数を経由しない）。"""
    return (now - EPOCH) // timedelta(milliseconds=1)


@dataclass(frozen=True)
class BucketResult:
    allowed: bool
    remaining: int  # このあと続けて使える回数
    retry_after_ms: int  # 拒否したとき、次の1回が使えるまでのミリ秒（通したときは 0）


@dataclass(frozen=True)
class Reservation:
    """仮押さえしたトークン。精算するときは、予約した日のキー（key）に対して行う。"""

    id: str
    key: str
    amount: int


@dataclass(frozen=True)
class QuotaState:
    used: int  # 精算済みの量
    reserved: int  # 精算待ちの予約の合計
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used - self.reserved)


@dataclass(frozen=True)
class ReserveResult:
    reservation: Reservation | None  # None なら上限を超えるので予約しなかった
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

    # ------------------------------------------------------------ レート制限（回数）

    async def take_request(self, user_id: str, limits: PlanLimits, now: datetime) -> BucketResult:
        rpm = limits.requests_per_minute
        capacity = rpm  # 満タンで1分ぶん（一度に続けて使える回数）
        ttl_ms = math.ceil(capacity * SCALE / rpm) + 1000  # 空から満タンに戻るまで。消えても「満タン」と同じ
        allowed, remaining, wait_ms = await self._bucket(
            keys=[self.bucket_key(user_id)], args=[capacity, rpm, epoch_ms(now), SCALE, ttl_ms])
        return BucketResult(bool(allowed), int(remaining), int(wait_ms))

    # ------------------------------------------------------------ クォータ（トークン量）

    async def reserve(self, user_id: str, limits: PlanLimits, amount: int, now: datetime,
                      hold_seconds: int) -> ReserveResult:
        rid = str(uuid7())
        key = self.quota_key(user_id, now)
        now_ms = epoch_ms(now)
        key_ttl_ms = epoch_ms(next_reset(now)) - now_ms + DAY_MS  # 日が変わったあとも1日は残す（調査用）
        ok, used, reserved = await self._reserve(
            keys=[key], args=[limits.tokens_per_day, amount, now_ms, rid, now_ms + hold_seconds * 1000, key_ttl_ms])
        state = QuotaState(int(used), int(reserved), limits.tokens_per_day)
        return ReserveResult(Reservation(rid, key, amount) if ok else None, state)

    async def settle(self, reservation: Reservation, actual_tokens: int) -> int | None:
        """予約を実際の量で精算し、その日の used を返す。もう精算済み（または期限切れ）なら None。"""
        used = await self._settle(keys=[reservation.key], args=[reservation.id, max(0, actual_tokens)])
        return None if int(used) < 0 else int(used)

    async def quota_state(self, user_id: str, limits: PlanLimits, now: datetime) -> QuotaState:
        """その日の使用量と、期限内の予約の合計（読むだけ。期限切れの予約は数えない）。"""
        flat = await self.redis.hgetall(self.quota_key(user_id, now))
        now_ms = epoch_ms(now)
        reserved = 0
        for field, value in flat.items():
            if field.startswith("r:"):
                held, expires = value.split(":")
                if int(expires) > now_ms:
                    reserved += int(held)
        return QuotaState(int(flat.get("used", 0)), reserved, limits.tokens_per_day)

    # ------------------------------------------------------------ 上流の 429（全員で共有する待ち時間）

    async def upstream_wait_ms(self, now: datetime) -> int:
        raw = await self.redis.get(self.cooldown_key)
        return 0 if raw is None else max(0, int(raw) - epoch_ms(now))

    async def note_upstream_429(self, retry_after_s: int, now: datetime) -> None:
        until = epoch_ms(now) + retry_after_s * 1000
        await self.redis.set(self.cooldown_key, until, px=retry_after_s * 1000 + 1000)
