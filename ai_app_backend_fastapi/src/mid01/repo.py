"""会話と発言の読み書き（リポジトリ）。session07/repo.py の append_turn を、何件でも足せる append_messages にしたもの。

ここでは commit しない：トランザクションの境界は呼び出し側が決める。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Conversation, Message, new_id
from .turn import StoredMessage


async def create_conversation(session: AsyncSession, *, user_id: str, title: str | None = None) -> Conversation:
    conv = Conversation(user_id=user_id, title=title)
    session.add(conv)
    await session.flush()  # INSERT を送り、DB 側の既定値（created_at など）を確定させる
    return conv


async def get_conversation(session: AsyncSession, conversation_id: str) -> Conversation | None:
    return await session.get(Conversation, conversation_id)


async def load_messages(session: AsyncSession, conversation_id: str) -> list[Message]:
    rows = await session.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq))
    return list(rows)


async def append_messages(session: AsyncSession, conversation_id: str,
                          rows: Sequence[StoredMessage]) -> list[Message]:
    """1往復ぶんの発言（user・assistant・tool_result だけの user …）を、seq の続きにまとめて足す。

    同じ会話への同時書き込みは、会話の行ロックで1つずつにする（seq の重複を防ぐ）。
    """
    await session.execute(select(Conversation.id).where(Conversation.id == conversation_id).with_for_update())
    last = await session.scalar(
        select(func.coalesce(func.max(Message.seq), 0)).where(Message.conversation_id == conversation_id))
    messages = [Message(id=r.id or new_id(), conversation_id=conversation_id, seq=last + i, role=r.role,
                        content=r.content, status=r.status, stop_reason=r.stop_reason)
                for i, r in enumerate(rows, start=1)]
    session.add_all(messages)
    await session.execute(update(Conversation).where(Conversation.id == conversation_id)
                          .values(updated_at=func.now()))
    await session.flush()
    return messages
