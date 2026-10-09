"""練習問題3の解答：発言 ID で1件取る関数と、自分の発言の総数を数える関数（どちらも持ち主の条件付き）。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Conversation, Message


async def get_message(session: AsyncSession, user_id: str, message_id: str) -> Message | None:
    # 発言には持ち主の列が無いので、会話を JOIN して会話の user_id で絞る
    return await session.scalar(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.id == message_id, Conversation.user_id == user_id))


async def count_messages(session: AsyncSession, user_id: str) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id))
    return count or 0
