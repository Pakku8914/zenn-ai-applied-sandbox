"""課金計測の台帳（usage_events）への記録（session13/metering.py のコピーを、問題4で組み直したもの）。

- record_usage / save_usage / save_quietly はセッション13のまま（ログだけ JSON の extra にした）
- metered()：中継（relay）を外側から包み、usage を送る前に記録する。途中で終わったら finally で見積もりを1行記録する
  セッション13の metered_events は relay_chat を中で作っていたが、ここでは出来上がった中継を受け取る。
  中継の作り方（Drain の締め切りの有無など）が変わっても、記録の約束は変わらないようにするため
- 台帳の outcome は CHECK 制約の4種だけ。中継の結末 drained（締め切りで閉じた）は cancelled として記録し、
  細かい理由はログの stream_closed に残す（request_id で突き合わせる。問題1）
クォータの精算（セッション10）は、この復習では省いている。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import anyio
from fastapi.sse import ServerSentEvent
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import UsageEvent, new_id
from .pricing import PriceTable, cost_usd
from .providers import Usage
from .relay import StreamOutcome

logger = logging.getLogger("kondate.review04.metering")

LEDGER_OUTCOME = {"drained": "cancelled"}  # 中継の結末 → 台帳の outcome（書いていないものはそのまま）


@dataclass(frozen=True)
class UsageRecord:
    request_id: str
    user_id: str
    model: str
    started_at: datetime
    usage: Usage
    usage_source: str  # upstream / estimated
    outcome: str  # completed / failed / client_disconnected / cancelled


def priced(record: UsageRecord, table: PriceTable) -> tuple[Decimal | None, date | None]:
    """(金額, 適用した単価の適用開始日)。単価が無ければ (None, None)。0 円にはしない。"""
    price = table.price_for(record.model, record.started_at)
    if price is None:
        logger.warning("usage_unpriced", extra={"request_id": record.request_id, "model": record.model,
                                                "started_at": record.started_at.isoformat()})
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
    """自分のセッションで1件を記録して commit する。取り消しの最中でもやり切るよう、シールドして待つ。"""
    with anyio.CancelScope(shield=True):
        async with factory() as session:
            saved = await record_usage(session, record, table)
            await session.commit()
            return saved


async def save_quietly(factory: async_sessionmaker[AsyncSession], record: UsageRecord, table: PriceTable) -> bool:
    """記録に失敗しても応答は止めない。あとから足せるよう、1行ぶんの全項目をログに残す。"""
    try:
        return await save_usage(factory, record, table)
    except Exception:
        u = record.usage
        logger.exception("usage_record_failed", extra={
            "request_id": record.request_id, "user_id": record.user_id, "model": record.model,
            "started_at": record.started_at.isoformat(), "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens, "cache_creation_input_tokens": u.cache_creation_input_tokens,
            "cache_read_input_tokens": u.cache_read_input_tokens, "usage_source": record.usage_source,
            "outcome": record.outcome})
        return False


@dataclass(frozen=True)
class Meter:
    """1回の要求を台帳に書くのに要るもの（ストリームの外で決まっている値）。"""

    factory: async_sessionmaker[AsyncSession]
    table: PriceTable
    user_id: str
    model: str  # 実際に答えた経路のモデル（問題7）
    started_at: datetime

    def record(self, outcome: StreamOutcome) -> UsageRecord:
        reason = outcome.reason or "cancelled"
        return UsageRecord(outcome.request_id, self.user_id, self.model, self.started_at,
                           outcome.usage or Usage(0, 0), outcome.usage_source or "estimated",
                           LEDGER_OUTCOME.get(reason, reason))


async def metered(events: AsyncIterator[ServerSentEvent], outcome: StreamOutcome,
                  meter: Meter) -> AsyncIterator[ServerSentEvent]:
    """中継をそのまま流し、どう終わっても台帳に1行を記録する。"""
    recorded = False
    try:
        async with aclosing(events):
            async for ev in events:
                if ev.event == "usage" and not recorded:
                    # 上流の usage を、クライアントに送る前に台帳へ
                    recorded = await save_quietly(meter.factory, meter.record(outcome), meter.table)
                yield ev
    finally:
        # ここに来た時点で、中継の finally は終わっている（aclosing が閉じた）。outcome には見積もりが入っている
        if not recorded:
            await save_quietly(meter.factory, meter.record(outcome), meter.table)
