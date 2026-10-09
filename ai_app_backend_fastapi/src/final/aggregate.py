"""台帳（usage_events）の集計（session13/aggregate.py のコピーから、final で使う関数だけを残したもの）。

日の区切りは JST の 0 時（Redis のクォータの「日」と同じ）。時刻は started_at（要求を受け付けた時刻）で数える。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kondate.clock import JST

from .models import UsageEvent

TOTAL_TOKENS = (UsageEvent.input_tokens + UsageEvent.output_tokens
                + UsageEvent.cache_creation_input_tokens + UsageEvent.cache_read_input_tokens)


def jst_date(now: datetime) -> date:
    return now.astimezone(JST).date()


def day_range(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tzinfo=JST)
    return start, start + timedelta(days=1)


def month_range(now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(JST)
    start = datetime(local.year, local.month, 1, tzinfo=JST)
    end = datetime(local.year + (local.month == 12), local.month % 12 + 1, 1, tzinfo=JST)
    return start, end


async def tokens_between(session: AsyncSession, user_id: str, start: datetime, end: datetime) -> int:
    stmt = (select(func.coalesce(func.sum(TOTAL_TOKENS), 0))
            .where(UsageEvent.user_id == user_id, UsageEvent.started_at >= start, UsageEvent.started_at < end))
    return int(await session.scalar(stmt))


async def used_today(session: AsyncSession, user_id: str, now: datetime) -> int:
    """今日（JST）のトークン総量。data-usage と GET /api/usage の used_today は、台帳（正）から数える。"""
    return await tokens_between(session, user_id, *day_range(jst_date(now)))


@dataclass(frozen=True)
class CostSum:
    priced_usd: Decimal
    unpriced: int


async def cost_between(session: AsyncSession, user_id: str, start: datetime, end: datetime) -> CostSum:
    stmt = (select(func.coalesce(func.sum(UsageEvent.cost_usd), 0),
                   func.count().filter(UsageEvent.cost_usd.is_(None)))
            .where(UsageEvent.user_id == user_id, UsageEvent.started_at >= start, UsageEvent.started_at < end))
    total, unpriced = (await session.execute(stmt)).one()
    return CostSum(Decimal(total), int(unpriced))
