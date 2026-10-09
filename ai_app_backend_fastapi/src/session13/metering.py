"""課金計測の台帳（usage_events）への記録。final はこのファイルをコピーする。

- record_usage：1件を INSERT … ON CONFLICT (request_id) DO NOTHING で足す（同じ要求は何度書いても1行）
- save_usage / save_quietly：自分のセッションで記録して commit する（シールドするので切断の最中でもやり切る）
- metered_events：ストリームを中継しながら、usage を送る前に記録する。途中で終わったら finally で見積もりを記録する
- recompute_costs：各行の started_at に効いていた単価で、金額を計算し直す
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import anyio
from fastapi import Request
from fastapi.sse import ServerSentEvent
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .limiter import Limiter, Reservation
from .models import UsageEvent, new_id
from .pricing import PriceTable, cost_usd
from .providers import Usage
from .ratelimit import settle, usage_tokens
from .relay import Primed, StreamOutcome, relay_chat

logger = logging.getLogger("kondate.session13.metering")


@dataclass(frozen=True)
class UsageRecord:
    """台帳の1行のもと（金額は記録するときに単価表から計算する）。"""

    request_id: str
    user_id: str
    model: str
    started_at: datetime  # 要求を受け付けた時刻（Clock）。日・月の区切りと単価の選択に使う
    usage: Usage
    usage_source: str  # upstream / estimated
    outcome: str  # completed / failed / client_disconnected / cancelled


def priced(record: UsageRecord, table: PriceTable) -> tuple[Decimal | None, date | None]:
    """(金額, 適用した単価の適用開始日)。単価が無ければ (None, None)。

    0 円にはしない：0 にすると取りこぼしが集計に紛れて見えなくなる。行は cost_usd = NULL（単価なし）で残し、
    集計では unpriced として数え、単価表を直してから recompute_costs() で埋める。
    """
    price = table.price_for(record.model, record.started_at)
    if price is None:
        logger.warning("usage_unpriced request_id=%s model=%s started_at=%s", record.request_id, record.model,
                       record.started_at.isoformat())
        return None, None
    return cost_usd(record.usage, price), price.effective_from


async def record_usage(session: AsyncSession, record: UsageRecord, table: PriceTable) -> bool:
    """1件を台帳に足す。同じ request_id がもうあれば何もせず False を返す（commit は呼び出し側）。"""
    cost, price_from = priced(record, table)
    u = record.usage
    stmt = (insert(UsageEvent)
            .values(id=new_id(), request_id=record.request_id, user_id=record.user_id, model=record.model,
                    started_at=record.started_at, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                    cache_creation_input_tokens=u.cache_creation_input_tokens,
                    cache_read_input_tokens=u.cache_read_input_tokens, cost_usd=cost, price_from=price_from,
                    usage_source=record.usage_source, outcome=record.outcome)
            .on_conflict_do_nothing(index_elements=["request_id"])
            .returning(UsageEvent.id))
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def save_usage(factory: async_sessionmaker[AsyncSession], record: UsageRecord, table: PriceTable) -> bool:
    """自分のセッションで1件を記録して commit する。キャンセルの最中でも最後までやり切るよう、シールドして待つ。"""
    with anyio.CancelScope(shield=True):
        async with factory() as session:
            saved = await record_usage(session, record, table)
            await session.commit()
            return saved


async def save_quietly(factory: async_sessionmaker[AsyncSession], record: UsageRecord, table: PriceTable) -> bool:
    """記録に失敗しても、応答や精算は止めない。あとから足せるよう、1行ぶんの全項目をログに残す。"""
    try:
        return await save_usage(factory, record, table)
    except Exception:
        u = record.usage
        logger.exception("usage_record_failed request_id=%s user_id=%s model=%s started_at=%s input_tokens=%d "
                         "output_tokens=%d cache_creation_input_tokens=%d cache_read_input_tokens=%d "
                         "usage_source=%s outcome=%s", record.request_id, record.user_id, record.model,
                         record.started_at.isoformat(), u.input_tokens, u.output_tokens,
                         u.cache_creation_input_tokens, u.cache_read_input_tokens, record.usage_source,
                         record.outcome)
        return False


@dataclass(frozen=True)
class Meter:
    """1回の要求を台帳に書くのに要るもの（ストリームの外で決まっている値）。"""

    factory: async_sessionmaker[AsyncSession]
    table: PriceTable
    user_id: str
    model: str
    started_at: datetime

    def record(self, outcome: StreamOutcome) -> UsageRecord:
        return UsageRecord(outcome.request_id, self.user_id, self.model, self.started_at,
                           outcome.usage or Usage(0, 0), outcome.usage_source or "estimated",
                           outcome.reason or "cancelled")


async def metered_events(request: Request, primed: Primed, outcome: StreamOutcome, limiter: Limiter,
                         reservation: Reservation, meter: Meter) -> AsyncIterator[ServerSentEvent]:
    """relay_chat をそのまま流し、どう終わっても台帳に1行・クォータの精算を1回だけ行う。"""
    recorded = False
    events = relay_chat(request, primed, outcome)
    try:
        async with aclosing(events):
            async for ev in events:
                if ev.event == "usage" and not recorded:
                    # 上流の usage を、クライアントに送る前に台帳へ（このあとの used_today に今回の分が入る）
                    recorded = await save_quietly(meter.factory, meter.record(outcome), meter.table)
                yield ev
    finally:
        try:
            if not recorded:  # 途中失敗・切断・キャンセル：relay_chat の finally が見積もりを outcome に入れてある
                await save_quietly(meter.factory, meter.record(outcome), meter.table)
        finally:
            actual = usage_tokens(outcome.usage) if outcome.usage is not None else 0
            await settle(limiter, reservation, actual)


async def recompute_costs(session: AsyncSession, table: PriceTable, *, since: datetime | None = None) -> int:
    """各行の started_at に効いていた単価で金額を計算し直し、変わった行数を返す（commit は呼び出し側）。"""
    stmt = select(UsageEvent).order_by(UsageEvent.started_at)
    if since is not None:
        stmt = stmt.where(UsageEvent.started_at >= since)
    changed = 0
    for ev in (await session.scalars(stmt)).all():
        price = table.price_for(ev.model, ev.started_at)
        cost, price_from = (cost_usd(ev.usage, price), price.effective_from) if price else (None, None)
        if (cost, price_from) != (ev.cost_usd, ev.price_from):
            ev.cost_usd, ev.price_from = cost, price_from
            changed += 1
    return changed
