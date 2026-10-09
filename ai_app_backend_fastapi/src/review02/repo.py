"""会話と発言の読み書き。session07/repo.py のコピーの append_turn() を、1往復で複数の発言を足す
append_messages() に置き換えたもの（問題6）。

ここでは commit しない：トランザクションの境界は呼び出し側が決める。
"""

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


async def append_messages(session: AsyncSession, conversation_id: str, messages: list[dict], *,
                          final_id: str) -> list[Message]:
    """1往復ぶんの発言（user と、ループで増えた assistant・tool_result の user）を seq の続きに足す。

    最後の assistant の ID を final_id にする（start イベントで先に知らせた message_id と一致させる）。
    同じ会話への同時書き込みは、セッション7と同じく会話の行ロックで1つずつにする。
    """
    await session.execute(select(Conversation.id).where(Conversation.id == conversation_id).with_for_update())
    last = await session.scalar(
        select(func.coalesce(func.max(Message.seq), 0)).where(Message.conversation_id == conversation_id))
    final = max(i for i, m in enumerate(messages) if m["role"] == "assistant")
    rows = [Message(id=final_id if i == final else new_id(), conversation_id=conversation_id, seq=last + 1 + i,
                    role=m["role"], content=as_blocks(m["content"])) for i, m in enumerate(messages)]
    session.add_all(rows)
    await session.execute(update(Conversation).where(Conversation.id == conversation_id)
                          .values(updated_at=func.now()))
    await session.flush()
    return rows


def to_api_messages(rows: list[Message]) -> list[dict]:
    """保存した行を、そのまま LLM に送れる Anthropic 形式の messages にする。"""
    return [{"role": r.role, "content": r.content} for r in rows]
