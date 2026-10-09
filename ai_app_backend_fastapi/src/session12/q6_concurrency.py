"""練習問題6の解答：利用者ごとに、同時に動かせるジョブの数を制限する（free 1・pro 2）。"""

from __future__ import annotations

from redis.asyncio import Redis

from .errors import ApiError
from .keys import CurrentUser

ACQUIRE_LUA = """
-- KEYS[1]: 利用者の実行中ジョブの集合  ARGV[1]: job_id  ARGV[2]: 上限  ARGV[3]: 集合の寿命（秒）
if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 then return 1 end  -- 同じジョブの2回目は数えない
if redis.call('SCARD', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
redis.call('SADD', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""

LIMITS = {"free": 1, "pro": 2}
RETRY_AFTER = 10  # 1つ終わるまでの目安（秒）


class ActiveJobs:
    def __init__(self, redis: Redis, prefix: str = "s12:q6:") -> None:
        self.redis, self.prefix = redis, prefix
        self._acquire = redis.register_script(ACQUIRE_LUA)

    def key(self, user_id: str) -> str:
        return f"{self.prefix}active:{user_id}"

    async def acquire(self, user_id: str, job_id: str, limit: int, ttl: int) -> bool:
        return bool(await self._acquire(keys=[self.key(user_id)], args=[job_id, limit, ttl]))

    async def release(self, user_id: str, job_id: str) -> None:
        await self.redis.srem(self.key(user_id), job_id)

    async def count(self, user_id: str) -> int:
        return await self.redis.scard(self.key(user_id))


async def admit(active: ActiveJobs, user: CurrentUser, job_id: str, *, ttl: int) -> None:
    """枠が空いていなければ 429 rate_limited（retry-after 付き）。POST でジョブを積む前に呼ぶ。"""
    if not await active.acquire(user.id, job_id, LIMITS.get(user.plan, 1), ttl):
        raise ApiError(429, "rate_limited", headers={"retry-after": str(RETRY_AFTER)})
