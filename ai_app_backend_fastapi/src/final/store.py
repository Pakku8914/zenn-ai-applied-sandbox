"""ジョブの状態・1日ごとの記録・進捗イベントを Redis に置く（session12/store.py のコピー。接頭辞だけ final: に変えた）。

キー：final:job:{job_id}（ハッシュ・正本）／final:job:{job_id}:days（1日ごとの記録）／final:job:{job_id}:events（ストリーム）
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from redis.asyncio import Redis

PREFIX = "final:"
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
TERMINAL_EVENTS = frozenset({"done", "error", "cancelled"})
NOT_RUNNING = -1
ALREADY_RECORDED = -2

START_LUA = """
local status = redis.call('HGET', KEYS[1], 'status')
if not status then return 'missing' end
if status ~= 'queued' then return status end
redis.call('HSET', KEYS[1], 'status', 'running')
local total = redis.call('HGET', KEYS[1], 'total')
redis.call('XADD', KEYS[3], '*', 'event', 'progress', 'data', '{"done": 0, "total": ' .. total .. '}')
local ttl = redis.call('TTL', KEYS[1])
if ttl > 0 then redis.call('EXPIRE', KEYS[3], ttl) end
return 'running'
"""

ADVANCE_LUA = """
if redis.call('HGET', KEYS[1], 'status') ~= 'running' then return -1 end
if redis.call('HSETNX', KEYS[2], ARGV[1], ARGV[2]) == 0 then return -2 end
local done = redis.call('HINCRBY', KEYS[1], 'done', 1)
local total = redis.call('HGET', KEYS[1], 'total')
redis.call('XADD', KEYS[3], '*', 'event', 'progress', 'data', '{"done": ' .. done .. ', "total": ' .. total .. '}')
local ttl = redis.call('TTL', KEYS[1])
if ttl > 0 then
  redis.call('EXPIRE', KEYS[2], ttl)
  redis.call('EXPIRE', KEYS[3], ttl)
end
return done
"""

FINISH_LUA = """
local status = redis.call('HGET', KEYS[1], 'status')
if status ~= 'running' then return status end
local event, data
if ARGV[1] == 'succeeded' then
  redis.call('HSET', KEYS[1], 'result', ARGV[2])
  event, data = 'done', '{"result": ' .. ARGV[2] .. '}'
elseif ARGV[1] == 'failed' then
  redis.call('HSET', KEYS[1], 'error', ARGV[2])
  event, data = 'error', ARGV[2]
else
  event = 'cancelled'
  data = '{"done": ' .. redis.call('HGET', KEYS[1], 'done') .. ', "total": ' .. redis.call('HGET', KEYS[1], 'total') .. '}'
end
redis.call('HSET', KEYS[1], 'status', ARGV[1])
redis.call('XADD', KEYS[3], '*', 'event', event, 'data', data)
for i = 1, 3 do redis.call('EXPIRE', KEYS[i], ARGV[3]) end
return ARGV[1]
"""

CANCEL_LUA = """
local status = redis.call('HGET', KEYS[1], 'status')
if status == 'queued' then
  redis.call('HSET', KEYS[1], 'status', 'cancelled', 'cancel_requested', '1')
  local total = redis.call('HGET', KEYS[1], 'total')
  redis.call('XADD', KEYS[3], '*', 'event', 'cancelled', 'data', '{"done": 0, "total": ' .. total .. '}')
  for i = 1, 3 do redis.call('EXPIRE', KEYS[i], ARGV[1]) end
  return 'cancelled'
end
if status == 'running' then
  redis.call('HSET', KEYS[1], 'cancel_requested', '1')
end
return status
"""


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    user_id: str
    status: str
    done: int
    total: int
    start_date: str
    work_seconds: float
    result_ttl: int
    request_id: str
    created_at: str
    cancel_requested: bool = False
    result: dict | None = None
    error: dict | None = None

    def to_hash(self) -> dict[str, str]:
        return {"user_id": self.user_id, "status": self.status, "done": str(self.done), "total": str(self.total),
                "start_date": self.start_date, "work_seconds": str(self.work_seconds),
                "result_ttl": str(self.result_ttl), "request_id": self.request_id,
                "created_at": self.created_at, "cancel_requested": "1" if self.cancel_requested else "0"}

    @classmethod
    def from_hash(cls, job_id: str, h: dict[str, str]) -> JobRecord:
        return cls(job_id=job_id, user_id=h["user_id"], status=h["status"], done=int(h["done"]),
                   total=int(h["total"]), start_date=h["start_date"], work_seconds=float(h["work_seconds"]),
                   result_ttl=int(h["result_ttl"]), request_id=h["request_id"], created_at=h["created_at"],
                   cancel_requested=h.get("cancel_requested") == "1",
                   result=json.loads(h["result"]) if "result" in h else None,
                   error=json.loads(h["error"]) if "error" in h else None)


@dataclass(frozen=True)
class JobEvent:
    id: str
    event: str
    data: str


class JobStore:
    def __init__(self, redis: Redis, prefix: str = PREFIX) -> None:
        self.redis, self.prefix = redis, prefix
        self._start = redis.register_script(START_LUA)
        self._advance = redis.register_script(ADVANCE_LUA)
        self._finish = redis.register_script(FINISH_LUA)
        self._cancel = redis.register_script(CANCEL_LUA)

    def keys(self, job_id: str) -> list[str]:
        base = f"{self.prefix}job:{job_id}"
        return [base, f"{base}:days", f"{base}:events"]

    async def create(self, job: JobRecord, *, ttl: int) -> None:
        key = self.keys(job.job_id)[0]
        async with self.redis.pipeline(transaction=True) as pipe:
            await pipe.hset(key, mapping=job.to_hash()).expire(key, ttl).execute()

    async def get(self, job_id: str) -> JobRecord | None:
        h = await self.redis.hgetall(self.keys(job_id)[0])
        return JobRecord.from_hash(job_id, h) if h else None

    async def status(self, job_id: str) -> str | None:
        return await self.redis.hget(self.keys(job_id)[0], "status")

    async def delete(self, job_id: str) -> None:
        await self.redis.delete(*self.keys(job_id))

    async def start(self, job_id: str) -> str:
        return await self._start(keys=self.keys(job_id))

    async def advance(self, job_id: str, index: int, day: dict) -> int:
        return int(await self._advance(keys=self.keys(job_id), args=[index, json.dumps(day, ensure_ascii=False)]))

    async def finish(self, job_id: str, status: str, value: str, ttl: int) -> str | None:
        return await self._finish(keys=self.keys(job_id), args=[status, value, ttl])

    async def cancel(self, job_id: str, *, ttl: int) -> str | None:
        return await self._cancel(keys=self.keys(job_id), args=[ttl])

    async def cancel_requested(self, job_id: str) -> bool:
        return await self.redis.hget(self.keys(job_id)[0], "cancel_requested") == "1"

    async def recorded_days(self, job_id: str) -> dict[int, dict]:
        raw = await self.redis.hgetall(self.keys(job_id)[1])
        return {int(k): json.loads(v) for k, v in raw.items()}

    async def read_events(self, job_id: str, after: str, *, block_ms: int | None = None) -> list[JobEvent]:
        resp = await self.redis.xread({self.keys(job_id)[2]: after}, count=100, block=block_ms)
        if not resp:
            return []
        [(_stream, entries)] = resp
        return [JobEvent(entry_id, fields["event"], fields["data"]) for entry_id, fields in entries]
