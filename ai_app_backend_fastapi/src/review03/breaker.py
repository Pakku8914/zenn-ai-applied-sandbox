"""サーキットブレーカ（閉→開→半開）を Redis で共有する（session11/breaker.py のコピー。キーは review03:cb:<経路>）。

- 状態は経路ごとのハッシュ1つに持ち、判定と更新を Lua スクリプト1本で原子的に行う
- 時刻はアプリの Clock から渡す（Lua の中で TIME を呼ばない）。FixedClock で「30秒後」を作って試験できる
- 複数の API サーバと worker が同じ Redis を見るので、1台で開けば全台が上流を呼ぶのをやめる
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis

PREFIX = "review03"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
KEY_TTL_MS = 86_400_000  # 使われなくなった経路のハッシュは1日で消える

BREAKER_LUA = """
-- サーキットブレーカ。KEYS[1]: 経路ごとのハッシュ（state・failures・opened_at・probe_until）
-- ARGV[1]: 操作（allow / success / failure） ARGV[2]: いまの時刻（ミリ秒。アプリの Clock）
-- ARGV[3]: 開くまでの連続失敗数 ARGV[4]: 開いている時間（ミリ秒） ARGV[5]: 試しの1回の持ち時間（ミリ秒）
-- ARGV[6]: キーの寿命（ミリ秒）
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
    state = 'half_open'                      -- 開いている時間が過ぎた：試しの1回だけ通す
    probe_until = now + tonumber(ARGV[5])
  elseif state == 'open' then
    allowed = 0
  elseif state == 'half_open' and now < probe_until then
    allowed = 0                              -- 試しの1回がまだ戻っていない
  elseif state == 'half_open' then
    probe_until = now + tonumber(ARGV[5])    -- 試しの1回が戻らなかった：この1回に任せ直す
  end
elseif op == 'success' then
  if state ~= 'open' then                    -- 開いた後に届いた古い成功では閉じない
    state = 'closed'
    failures = 0
    probe_until = 0
  end
elseif op == 'failure' then
  failures = failures + 1
  if state == 'half_open' or (state == 'closed' and failures >= tonumber(ARGV[3])) then
    state = 'open'                           -- 試しの1回が失敗した／続けて閾値まで失敗した
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
    """Clock の時刻を UNIX ミリ秒の整数にする（浮動小数を経由しない）。"""
    return (now - EPOCH) // timedelta(milliseconds=1)


@dataclass(frozen=True)
class BreakerConfig:
    failure_threshold: int = 5  # 続けてこの回数失敗したら開く
    open_seconds: float = 30.0  # 開いてから、試しの1回を通すまでの秒
    probe_seconds: float = 10.0  # 試しの1回の持ち時間。戻らなければ次の1回に任せる


@dataclass(frozen=True)
class BreakerState:
    state: str  # closed / open / half_open
    allowed: bool  # allow() のとき：上流を呼んでよいか（success・failure では常に True）
    failures: int  # 続けて失敗した回数


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
        """上流を呼ぶ前に聞く。開いていれば allowed=False（半開なら試しの1回だけ True）。"""
        return await self._call("allow", now)

    async def record_success(self, now: datetime) -> BreakerState:
        return await self._call("success", now)

    async def record_failure(self, now: datetime) -> BreakerState:
        return await self._call("failure", now)
