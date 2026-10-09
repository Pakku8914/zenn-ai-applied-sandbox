"""会話履歴の ORM モデル。session07/models.py のコピー（スキーマを review02 に変えた）。

復習2ではテーブルを setup_db.py の create_all で作る（変更の管理は Alembic で行う。セッション7）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import uuid_utils
from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, Index, Integer, MetaData, String, UniqueConstraint,
                        Uuid, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "review02"


def new_id() -> str:
    """UUIDv7 を文字列で返す（先頭48ビットが作成時刻のミリ秒なので、作った順にほぼ並ぶ）。"""
    return str(uuid_utils.uuid7())


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)  # この章のテーブルはすべてスキーマ review02 に置く


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_id_updated_at", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(16))  # 持つだけ。誰の会話かを確かめるのは認証のセッションで
    title: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        # 会話の中の順番は seq で持つ。この一意制約の索引が「会話ごとに seq 順で読む」検索にも効く
        UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_id_seq"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        CheckConstraint("status IN ('complete', 'partial')", name="ck_messages_status"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey(f"{SCHEMA}.conversations.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    # Anthropic 形式の content ブロックの配列をそのまま入れる（text・tool_use・tool_result …）
    content: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="complete", server_default="complete")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
