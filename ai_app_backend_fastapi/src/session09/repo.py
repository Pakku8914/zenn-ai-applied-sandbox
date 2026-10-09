"""会話と発言の読み書き（session07 の repo.py をコピーし、すべての関数に user_id の条件を足したもの）。

公開関数は必ず user_id を受け取り、WHERE に入れる。他人の会話は「存在しない」と同じ None / False を返す。
ここでは commit しない：トランザクションの境界は呼び出し側が決める。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Conversation, Message, new_id

Blocks = list[dict[str, Any]]


def as_blocks(content: str | Blocks) -> Blocks:
    """文字列の content を text ブロック1個の配列にそろえる（保存する形を1種類にする）。"""
    return [{"type": "text", "text": content}] if isinstance(content, str) else content


async def create_conversation(session: AsyncSession, *, user_id: str, title: str | None = None) -> Conversation:
    conv = Conversation(user_id=user_id, title=title)
    session.add(conv)
    await session.flush()
    return conv


async def get_conversation(session: AsyncSession, user_id: str, conversation_id: str) -> Conversation | None:
    # session.get(Conversation, id) で取ってから持ち主を比べるのではなく、最初から WHERE に入れる
    return await session.scalar(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id))


async def list_conversations(session: AsyncSession, user_id: str, *, limit: int = 20) -> list[Conversation]:
    rows = await session.scalars(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(limit))
    return list(rows)


async def rename_conversation(session: AsyncSession, user_id: str, conversation_id: str,
                              title: str) -> Conversation | None:
    conv = await get_conversation(session, user_id, conversation_id)
    if conv is None:
        return None
    conv.title = title
    await session.flush()
    return conv


async def delete_conversation(session: AsyncSession, user_id: str, conversation_id: str) -> bool:
    """消せたら True。発言は外部キーの ON DELETE CASCADE で一緒に消える。"""
    deleted = await session.scalar(
        delete(Conversation)
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .returning(Conversation.id))
    return deleted is not None


async def load_messages(session: AsyncSession, user_id: str, conversation_id: str) -> list[Message]:
    # 会話の持ち主を JOIN で確かめる（会話 ID だけで発言を読める関数を作らない）
    rows = await session.scalars(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.conversation_id == conversation_id, Conversation.user_id == user_id)
        .order_by(Message.seq))
    return list(rows)


async def append_turn(session: AsyncSession, user_id: str, conversation_id: str, *, user_content: str | Blocks,
                      assistant_content: Blocks, assistant_id: str | None = None,
                      status: str = "complete") -> tuple[Message, Message] | None:
    """user と assistant の発言を1往復ぶん足す。自分の会話でなければ何もせず None。"""
    locked = await session.scalar(
        select(Conversation.id)
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .with_for_update())
    if locked is None:
        return None
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
