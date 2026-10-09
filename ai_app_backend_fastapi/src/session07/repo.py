"""会話と発言の読み書き（リポジトリ）。ここでは commit しない：トランザクションの境界は呼び出し側が決める。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Conversation, Message, new_id

Blocks = list[dict[str, Any]]


def as_blocks(content: str | Blocks) -> Blocks:
    """文字列の content を text ブロック1個の配列にそろえる（保存する形を1種類にする）。"""
    return [{"type": "text", "text": content}] if isinstance(content, str) else content


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


async def append_turn(session: AsyncSession, conversation_id: str, *, user_content: str | Blocks,
                      assistant_content: Blocks, assistant_id: str | None = None,
                      status: str = "complete") -> tuple[Message, Message]:
    """user と assistant の発言を1往復ぶん足す。同じ会話への同時書き込みは行ロックで1つずつにする。"""
    await session.execute(select(Conversation.id).where(Conversation.id == conversation_id).with_for_update())
    last = await session.scalar(
        select(func.coalesce(func.max(Message.seq), 0)).where(Message.conversation_id == conversation_id))
    user = Message(conversation_id=conversation_id, seq=last + 1, role="user", content=as_blocks(user_content))
    assistant = Message(id=assistant_id or new_id(), conversation_id=conversation_id, seq=last + 2,
                        role="assistant", content=assistant_content, status=status)
    session.add_all([user, assistant])
    await session.execute(update(Conversation).where(Conversation.id == conversation_id)
                          .values(updated_at=func.now()))
    await session.flush()
    return user, assistant


def to_api_messages(rows: list[Message]) -> list[dict]:
    """保存した行を、そのまま LLM に送れる Anthropic 形式の messages にする。"""
    return [{"role": r.role, "content": r.content} for r in rows]
