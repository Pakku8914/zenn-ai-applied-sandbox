"""練習問題1の解答：request_id で、自分の記録だけを1件引く（問い合わせ対応用）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import UsageEvent


@dataclass(frozen=True)
class EventView:
    request_id: str
    started_at: datetime
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: Decimal | None
    usage_source: str
    outcome: str


async def find_event(session: AsyncSession, user_id: str, request_id: str) -> EventView | None:
    """他人の request_id を渡されても、存在を知らせない（None を返す。API にするなら 404）。"""
    ev = await session.scalar(
        select(UsageEvent).where(UsageEvent.request_id == request_id, UsageEvent.user_id == user_id))
    if ev is None:
        return None
    return EventView(ev.request_id, ev.started_at, ev.input_tokens, ev.output_tokens,
                     ev.cache_creation_input_tokens, ev.cache_read_input_tokens, ev.cost_usd,
                     ev.usage_source, ev.outcome)
