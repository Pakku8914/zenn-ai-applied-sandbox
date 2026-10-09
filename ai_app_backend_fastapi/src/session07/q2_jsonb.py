"""練習問題2の解答：JSONB の中身で発言を絞り込む。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Message


async def count_tool_messages(session: AsyncSession, conversation_id: str) -> int:
    """tool_use ブロックを1つ以上含む発言の数。content @> '[{"type": "tool_use"}]' で DB 側で数える。"""
    count = await session.scalar(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conversation_id,
            Message.content.contains([{"type": "tool_use"}])))
    return count or 0


async def tool_names(session: AsyncSession, conversation_id: str) -> list[str]:
    """呼ばれたツールの名前を、呼ばれた順に返す（絞り込みは DB、ブロックの取り出しは Python）。"""
    rows = await session.scalars(
        select(Message.content).where(
            Message.conversation_id == conversation_id,
            Message.content.contains([{"type": "tool_use"}])).order_by(Message.seq))
    return [b["name"] for content in rows for b in content if b.get("type") == "tool_use"]
