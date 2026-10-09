"""練習問題5の解答：台帳（正）から、Redis のその日の使用量を作り直す。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .aggregate import day_range, jst_date, tokens_between
from .limiter import Limiter


async def reconcile_quota(limiter: Limiter, session: AsyncSession, user_id: str,
                          now: datetime) -> tuple[int, int]:
    """(作り直す前の Redis の used, 台帳の used) を返す。予約（r:…）には触れず、used だけを台帳の値にする。"""
    db_used = await tokens_between(session, user_id, *day_range(jst_date(now)))
    key = limiter.quota_key(user_id, now)
    before = int(await limiter.redis.hget(key, "used") or 0)
    if before != db_used:
        await limiter.redis.hset(key, "used", db_used)
        await limiter.redis.pexpire(key, limiter.quota_ttl_ms(now))
    return before, db_used
