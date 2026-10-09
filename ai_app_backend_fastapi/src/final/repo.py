"""会話と発言の読み書き（mid01/repo.py のコピーに、持ち主と chat_id・履歴のずれの片付けを足したもの）。

LLM へ送る履歴の正は「受け取った UIMessage[]」（AI SDK の作法。②の再生成・編集はクライアントが履歴を切って送る）。
DB は「この利用者に何を届けたか」の記録で、GET /api/conversations/{id} の元になる。
そこで保存のたびに、クライアントの履歴に残っている assistant の ID を手がかりに、DB 側の後ろの発言を落としてから足す
（再生成で捨てられた古い応答が、会話の記録に残り続けないように）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import Conversation, Message, new_id
from .turn import StoredMessage

logger = logging.getLogger("kondate.final.repo")


def uuid_like(values: Sequence[str]) -> list[str]:
    """UUID として読めるものだけ（AI SDK が振った ID は UUID ではないので、UUID 型の列と比べる前に外す）。"""
    out: list[str] = []
    for v in values:
        try:
            uuid.UUID(v)
        except ValueError:
            continue
        out.append(v)
    return out


async def find_conversation(session: AsyncSession, user_id: str, chat_id: str) -> Conversation | None:
    """持ち主の条件を必ず付けて探す。他人の会話は「無い」のと同じ結果になる（存在を教えない）。"""
    return await session.scalar(
        select(Conversation).where(Conversation.user_id == user_id, Conversation.chat_id == chat_id))


async def list_conversations(session: AsyncSession, user_id: str, *, limit: int = 50) -> list[Conversation]:
    rows = await session.scalars(select(Conversation).where(Conversation.user_id == user_id)
                                 .order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit))
    return list(rows)


async def load_messages(session: AsyncSession, conversation_id: str) -> list[Message]:
    rows = await session.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq))
    return list(rows)


async def partial_ids(session: AsyncSession, user_id: str, chat_id: str, ids: Sequence[str]) -> set[str]:
    """受け取った assistant の ID のうち、DB で status=partial のもの（LLM に「途中で切れた」と伝えるため）。"""
    candidates = uuid_like(ids)
    if not candidates:
        return set()
    rows = await session.scalars(
        select(Message.id).join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id, Conversation.chat_id == chat_id,
               Message.id.in_(candidates), Message.status == "partial"))
    return set(rows)


async def lock_conversation(session: AsyncSession, user_id: str, chat_id: str, title: str | None) -> str:
    """会話が無ければ作り、行ロックを取って主キーを返す（同じ会話への同時保存を1つずつにする）。"""
    await session.execute(insert(Conversation)
                          .values(id=new_id(), user_id=user_id, chat_id=chat_id, title=title)
                          .on_conflict_do_nothing(index_elements=["user_id", "chat_id"]))
    conversation_id = await session.scalar(
        select(Conversation.id).where(Conversation.user_id == user_id, Conversation.chat_id == chat_id)
        .with_for_update())
    assert conversation_id is not None
    return conversation_id


async def truncate_after(session: AsyncSession, conversation_id: str, keep_ids: Sequence[str]) -> int:
    """クライアントの履歴に残っている assistant のうち、いちばん後ろのものより後ろの発言を消す。消した件数を返す。"""
    ids = uuid_like(keep_ids)
    cut = 0
    if ids:
        cut = await session.scalar(
            select(func.coalesce(func.max(Message.seq), 0))
            .where(Message.conversation_id == conversation_id, Message.id.in_(ids), Message.role == "assistant"))
    result = await session.execute(
        delete(Message).where(Message.conversation_id == conversation_id, Message.seq > cut))
    return result.rowcount or 0


async def append_messages(session: AsyncSession, conversation_id: str,
                          rows: Sequence[StoredMessage]) -> list[Message]:
    """1往復ぶんの発言を、seq の続きにまとめて足す（行ロックは lock_conversation で取ってある）。"""
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


async def save_turn(factory: async_sessionmaker[AsyncSession], *, user_id: str, chat_id: str, title: str | None,
                    keep_ids: Sequence[str], rows: Sequence[StoredMessage]) -> bool:
    """1往復を1つのトランザクションで保存する（会話の作成・ずれの片付け・追加）。ストリーミングの後なので短いセッションで。"""
    try:
        async with factory() as session:
            conversation_id = await lock_conversation(session, user_id, chat_id, title)
            await truncate_after(session, conversation_id, keep_ids)
            await append_messages(session, conversation_id, rows)
            await session.commit()
    except SQLAlchemyError:
        logger.exception("save_turn_failed", extra={"chat_id": chat_id})
        return False
    return True
