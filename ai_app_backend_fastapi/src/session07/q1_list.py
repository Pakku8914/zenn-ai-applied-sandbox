"""練習問題1の解答：ユーザーの会話一覧（新しく更新された順）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Conversation


async def list_conversations(session: AsyncSession, user_id: str, *, limit: int = 20) -> list[Conversation]:
    # 索引 (user_id, updated_at) をそのまま逆順に読める並べ方。同時刻のときは id（UUIDv7）で順番を決める
    rows = await session.scalars(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(limit))
    return list(rows)
