"""冪等キー（Idempotency-Key）：同じ要求を2回送られても、処理を2回しない（session11/idempotency.py のコピー）。

記録は review03:idem:<scope>:<キー> のハッシュ1つ：
  state（processing＝処理中 / done＝完了）・fp（要求の指紋）・owner（処理中の持ち主）・status・body・fallback
- begin：無ければ processing で作る（new）。あれば指紋を比べ、違えば conflict、処理中なら in_progress、完了なら replay
- complete：持ち主が自分のときだけ、応答を保存して寿命を 24 時間に延ばす
- abandon：持ち主が自分のときだけ消す（失敗した要求は、同じキーでやり直せる）
scope には利用者 ID を入れる（ほかの人の応答を再生しないため）。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from redis.asyncio import Redis
from uuid_utils import uuid7

PREFIX = "review03"
PROCESSING_TTL_MS = 60_000  # 処理中の記録の寿命。落ちたプロセスの分は消える
DONE_TTL_MS = 86_400_000  # 完了した応答を覚えておく時間（24時間）
KEY_PATTERN = re.compile(r"^[\x21-\x7e]{1,255}$")  # 空白を含まない ASCII の1〜255文字

BEGIN_LUA = """
-- KEYS[1]: 冪等キーの記録  ARGV[1]: 要求の指紋  ARGV[2]: 持ち主  ARGV[3]: 処理中の寿命（ミリ秒）
local cur = redis.call('HMGET', KEYS[1], 'state', 'fp', 'status', 'body', 'fallback')
if not cur[1] then
  redis.call('HSET', KEYS[1], 'state', 'processing', 'fp', ARGV[1], 'owner', ARGV[2])
  redis.call('PEXPIRE', KEYS[1], ARGV[3])
  return {'new'}
end
if cur[2] ~= ARGV[1] then
  return {'conflict'}
end
if cur[1] == 'processing' then
  return {'in_progress'}
end
return {'replay', cur[3], cur[4], cur[5] or ''}
"""

FINISH_LUA = """
-- KEYS[1]: 冪等キーの記録  ARGV[1]: 持ち主  ARGV[2]: 操作（complete / abandon）
-- ARGV[3]: status  ARGV[4]: body  ARGV[5]: fallback  ARGV[6]: 完了後の寿命（ミリ秒）
if redis.call('HGET', KEYS[1], 'owner') ~= ARGV[1] then
  return 0  -- 持ち主が違う（処理中の寿命が切れ、別の要求が引き継いだ）
end
if ARGV[2] == 'abandon' then
  redis.call('DEL', KEYS[1])
  return 1
end
redis.call('HSET', KEYS[1], 'state', 'done', 'status', ARGV[3], 'body', ARGV[4], 'fallback', ARGV[5])
redis.call('PEXPIRE', KEYS[1], ARGV[6])
return 1
"""


def fingerprint(method: str, path: str, body: dict) -> str:
    """要求の指紋。キーの順序や空白に左右されないよう、整列した JSON にしてから SHA-256 を取る。"""
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{method} {path}\n{canonical}".encode()).hexdigest()


@dataclass(frozen=True)
class Ticket:
    """begin が new を返したときの引換券。complete か abandon に渡す。"""

    key: str
    owner: str


@dataclass(frozen=True)
class Saved:
    status: int
    body: str
    fallback: str | None


@dataclass(frozen=True)
class Begun:
    outcome: str  # new / replay / conflict / in_progress
    ticket: Ticket | None = None
    saved: Saved | None = None


class IdempotencyStore:
    def __init__(self, redis: Redis, prefix: str = PREFIX) -> None:
        self.redis = redis
        self.prefix = prefix
        self._begin = redis.register_script(BEGIN_LUA)
        self._finish = redis.register_script(FINISH_LUA)

    def record_key(self, scope: str, key: str) -> str:
        return f"{self.prefix}:idem:{scope}:{key}"

    async def begin(self, scope: str, key: str, fp: str) -> Begun:
        rkey = self.record_key(scope, key)
        owner = str(uuid7())
        res = await self._begin(keys=[rkey], args=[fp, owner, PROCESSING_TTL_MS])
        if res[0] == "new":
            return Begun("new", ticket=Ticket(rkey, owner))
        if res[0] == "replay":
            return Begun("replay", saved=Saved(int(res[1]), res[2], res[3] or None))
        return Begun(res[0])

    async def complete(self, ticket: Ticket, status: int, body: str, fallback: str | None) -> bool:
        done = await self._finish(keys=[ticket.key],
                                  args=[ticket.owner, "complete", status, body, fallback or "", DONE_TTL_MS])
        return bool(done)

    async def abandon(self, ticket: Ticket) -> bool:
        return bool(await self._finish(keys=[ticket.key], args=[ticket.owner, "abandon", "", "", "", 0]))
