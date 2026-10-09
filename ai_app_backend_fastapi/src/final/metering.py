"""課金計測の台帳（usage_events）への記録（session13/metering.py のコピー）。

最終プロジェクトでの変更（決定事項1）：
- 一意キーを request_id から turn_id に変えた。turn_id はこちらで採番した assistant の ID（UUIDv7）で、
  1往復（ツールループの全ステップ）につき1行になる。どう終わっても、usage を送る前の記録と finally の記録の
  両方が同じ turn_id で INSERT … ON CONFLICT DO NOTHING するので、行は1つしかできない
- request_id は相関用に残す。②が同じ x-request-id を何度送ってきても、記録は落ちない
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import anyio
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import UsageEvent, new_id
from .pricing import PriceTable, cost_usd
from .providers import Usage

logger = logging.getLogger("kondate.final.metering")


@dataclass(frozen=True)
class UsageRecord:
    turn_id: str
    request_id: str
    user_id: str
    model: str
    started_at: datetime
    usage: Usage
    usage_source: str  # upstream / estimated
    outcome: str  # completed / failed / cancelled / rejected


def priced(record: UsageRecord, table: PriceTable) -> tuple[Decimal | None, date | None]:
    """(金額, 適用した単価の適用開始日)。単価が無ければ 0 円にせず (None, None)。"""
    price = table.price_for(record.model, record.started_at)
    if price is None:
        logger.warning("usage_unpriced", extra={"turn_id": record.turn_id, "model": record.model})
        return None, None
    return cost_usd(record.usage, price), price.effective_from


async def record_usage(session: AsyncSession, record: UsageRecord, table: PriceTable) -> bool:
    cost, price_from = priced(record, table)
    u = record.usage
    stmt = (insert(UsageEvent)
            .values(id=new_id(), turn_id=record.turn_id, request_id=record.request_id, user_id=record.user_id,
                    model=record.model, started_at=record.started_at, input_tokens=u.input_tokens,
                    output_tokens=u.output_tokens, cache_creation_input_tokens=u.cache_creation_input_tokens,
                    cache_read_input_tokens=u.cache_read_input_tokens, cost_usd=cost, price_from=price_from,
                    usage_source=record.usage_source, outcome=record.outcome)
            .on_conflict_do_nothing(index_elements=["turn_id"])
            .returning(UsageEvent.id))
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def save_quietly(factory: async_sessionmaker[AsyncSession], record: UsageRecord, table: PriceTable) -> bool:
    """自分のセッションで1件を記録して commit する。失敗しても応答は止めず、1行ぶんの全項目をログに残す。"""
    try:
        with anyio.CancelScope(shield=True):
            async with factory() as session:
                saved = await record_usage(session, record, table)
                await session.commit()
                return saved
    except Exception:
        u = record.usage
        logger.exception("usage_record_failed", extra={
            "turn_id": record.turn_id, "user_id": record.user_id, "model": record.model,
            "started_at": record.started_at.isoformat(), "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens, "cache_creation_input_tokens": u.cache_creation_input_tokens,
            "cache_read_input_tokens": u.cache_read_input_tokens, "usage_source": record.usage_source,
            "outcome": record.outcome})
        return False
