"""台帳（usage_events）の集計。final はこのファイルをコピーする。

日の区切りは JST の 0 時（Redis のクォータの「日」と同じ）。時刻は started_at（要求を受け付けた時刻）で数える。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Date, cast, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from kondate.clock import JST

from .keys import CurrentUser
from .models import UsageEvent
from .plans import PlanLimits

# timestamptz を「UTC+9 の壁時計」に直してから日付にする（DB のタイムゾーン設定や tz データに頼らない）
JST_DAY = cast(func.timezone(literal_column("INTERVAL '+09:00'"), UsageEvent.started_at), Date).label("day")
TOTAL_TOKENS = (UsageEvent.input_tokens + UsageEvent.output_tokens
                + UsageEvent.cache_creation_input_tokens + UsageEvent.cache_read_input_tokens)


def jst_date(now: datetime) -> date:
    return now.astimezone(JST).date()


def day_range(day: date) -> tuple[datetime, datetime]:
    """JST のその日の [00:00, 翌日 00:00)。"""
    start = datetime.combine(day, time(0), tzinfo=JST)
    return start, start + timedelta(days=1)


def month_range(now: datetime) -> tuple[datetime, datetime]:
    """JST のその月の [1日 00:00, 翌月1日 00:00)。"""
    local = now.astimezone(JST)
    start = datetime(local.year, local.month, 1, tzinfo=JST)
    end = datetime(local.year + (local.month == 12), local.month % 12 + 1, 1, tzinfo=JST)
    return start, end


async def tokens_between(session: AsyncSession, user_id: str, start: datetime, end: datetime) -> int:
    """[start, end) のトークン総量（入力・出力・キャッシュの読み書き。クォータと同じ数え方）。"""
    stmt = (select(func.coalesce(func.sum(TOTAL_TOKENS), 0))
            .where(UsageEvent.user_id == user_id, UsageEvent.started_at >= start, UsageEvent.started_at < end))
    return int(await session.scalar(stmt))


@dataclass(frozen=True)
class CostSum:
    priced_usd: Decimal  # 金額の分かる行の合計
    unpriced: int  # 単価が無く cost_usd が NULL の行の数（0 円として足し込まない）


UNPRICED = func.count().filter(UsageEvent.cost_usd.is_(None))


async def cost_between(session: AsyncSession, user_id: str, start: datetime, end: datetime) -> CostSum:
    """[start, end) の金額の合計と、金額の分からない行の数。"""
    stmt = (select(func.coalesce(func.sum(UsageEvent.cost_usd), 0), UNPRICED)
            .where(UsageEvent.user_id == user_id, UsageEvent.started_at >= start, UsageEvent.started_at < end))
    total, unpriced = (await session.execute(stmt)).one()
    return CostSum(Decimal(total), int(unpriced))


async def usage_today(session: AsyncSession, user: CurrentUser, limits: PlanLimits, now: datetime) -> dict:
    """API契約④ の {plan, used_today, limit_today, requests_per_minute}。used_today は台帳（正）から数える。"""
    used = await tokens_between(session, user.id, *day_range(jst_date(now)))
    return {"plan": user.plan, "used_today": used, "limit_today": limits.tokens_per_day,
            "requests_per_minute": limits.requests_per_minute}


@dataclass(frozen=True)
class DayUsage:
    day: date
    requests: int
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: Decimal | None  # 金額の分かる行の合計。その日の行がすべて単価なしなら None（0 にしない）
    unpriced: int  # 単価が無く金額の分からない行の数。0 でなければ cost_usd は一部だけの合計


async def daily_usage(session: AsyncSession, user_id: str, first: date, last: date) -> list[DayUsage]:
    """1人の利用者の、first〜last（JST の日付・両端を含む）の日別の集計。記録の無い日は返さない。"""
    start, _ = day_range(first)
    _, end = day_range(last)
    stmt = (select(JST_DAY, func.count(), func.sum(UsageEvent.input_tokens), func.sum(UsageEvent.output_tokens),
                   func.sum(UsageEvent.cache_creation_input_tokens), func.sum(UsageEvent.cache_read_input_tokens),
                   func.sum(UsageEvent.cost_usd), UNPRICED)
            .where(UsageEvent.user_id == user_id, UsageEvent.started_at >= start, UsageEvent.started_at < end)
            .group_by(JST_DAY)
            .order_by(JST_DAY))
    rows = await session.execute(stmt)
    return [DayUsage(day, int(n), int(i), int(o), int(cw), int(cr), None if cost is None else Decimal(cost),
                     int(unpriced))
            for day, n, i, o, cw, cr, cost, unpriced in rows]
