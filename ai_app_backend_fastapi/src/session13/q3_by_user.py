"""練習問題3の解答：1日（JST）の利用者別の集計を、金額の多い順に並べる（運用者向け）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .aggregate import TOTAL_TOKENS, UNPRICED, day_range
from .models import UsageEvent


@dataclass(frozen=True)
class UserDay:
    user_id: str
    requests: int
    tokens: int
    cost_usd: Decimal | None  # 行がすべて単価なしなら None（0 にしない）
    unpriced: int  # 金額の分からない行の数


async def usage_by_user(session: AsyncSession, day: date, *, limit: int = 20) -> list[UserDay]:
    start, end = day_range(day)
    cost = func.sum(UsageEvent.cost_usd)
    stmt = (select(UsageEvent.user_id, func.count(), func.sum(TOTAL_TOKENS), cost, UNPRICED)
            .where(UsageEvent.started_at >= start, UsageEvent.started_at < end)
            .group_by(UsageEvent.user_id)
            .order_by(cost.desc().nulls_last(), UsageEvent.user_id)  # 金額の分からない人は最後に並べる
            .limit(limit))
    return [UserDay(uid, int(n), int(t), None if c is None else Decimal(c), int(u))
            for uid, n, t, c, u in await session.execute(stmt)]
