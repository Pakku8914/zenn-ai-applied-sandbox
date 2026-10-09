"""サーキットブレーカを Redis で共有する（session11/breaker.py のコピー。接頭辞だけ review04 にした）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis

PREFIX = "review04"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
KEY_TTL_MS = 86_400_000

BREAKER_LUA = """
local op = ARGV[1]
local now = tonumber(ARGV[2])
local s = redis.call('HMGET', KEYS[1], 'state', 'failures', 'opened_at', 'probe_until')
local state = s[1] or 'closed'
local failures = tonumber(s[2]) or 0
local opened_at = tonumber(s[3]) or 0
local probe_until = tonumber(s[4]) or 0
local allowed = 1
if op == 'allow' then
  if state == 'open' and now >= opened_at + tonumber(ARGV[4]) then
    state = 'half_open'
    probe_until = now + tonumber(ARGV[5])
  elseif state == 'open' then
    allowed = 0
  elseif state == 'half_open' and now < probe_until then
    allowed = 0
  elseif state == 'half_open' then
    probe_until = now + tonumber(ARGV[5])
  end
elseif op == 'success' then
  if state ~= 'open' then
    state = 'closed'
    failures = 0
    probe_until = 0
  end
elseif op == 'failure' then
  failures = failures + 1
  if state == 'half_open' or (state == 'closed' and failures >= tonumber(ARGV[3])) then
    state = 'open'
    opened_at = now
    probe_until = 0
  end
end
redis.call('HSET', KEYS[1], 'state', state, 'failures', tostring(failures),
           'opened_at', tostring(opened_at), 'probe_until', tostring(probe_until))
redis.call('PEXPIRE', KEYS[1], ARGV[6])
return {state, allowed, failures}
"""


def epoch_ms(now: datetime) -> int:
    return (now - EPOCH) // timedelta(milliseconds=1)


@dataclass(frozen=True)
class BreakerConfig:
    failure_threshold: int = 5
    open_seconds: float = 30.0
    probe_seconds: float = 10.0


@dataclass(frozen=True)
class BreakerState:
    state: str
    allowed: bool
    failures: int


class CircuitBreaker:
    def __init__(self, redis: Redis, name: str, config: BreakerConfig = BreakerConfig(),
                 prefix: str = PREFIX) -> None:
        self.redis = redis
        self.name = name
        self.config = config
        self.key = f"{prefix}:cb:{name}"
        self._script = redis.register_script(BREAKER_LUA)

    async def _call(self, op: str, now: datetime) -> BreakerState:
        c = self.config
        state, allowed, failures = await self._script(
            keys=[self.key],
            args=[op, epoch_ms(now), c.failure_threshold, round(c.open_seconds * 1000),
                  round(c.probe_seconds * 1000), KEY_TTL_MS])
        return BreakerState(str(state), bool(allowed), int(failures))

    async def allow(self, now: datetime) -> BreakerState:
        return await self._call("allow", now)

    async def record_success(self, now: datetime) -> BreakerState:
        return await self._call("success", now)

    async def record_failure(self, now: datetime) -> BreakerState:
        return await self._call("failure", now)
