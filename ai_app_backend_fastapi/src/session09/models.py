"""ユーザー・API キー・会話の ORM モデル（スキーマ s09）。テーブルの作成・変更は Alembic のマイグレーションで行う。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import uuid_utils
from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, Index, Integer, MetaData, String, UniqueConstraint,
                        Uuid, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "s09"


def new_id() -> str:
    """UUIDv7 を文字列で返す（先頭48ビットが作成時刻のミリ秒なので、作った順にほぼ並ぶ）。"""
    return str(uuid_utils.uuid7())


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)  # このセッションのテーブルはすべてスキーマ s09 に置く


class User(Base):
    """data/users.json の利用者。plan はレート制限のセッションで使う（ここでは持つだけ）。"""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("plan IN ('free', 'pro')", name="ck_users_plan"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    plan: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    """API キー。平文は保存しない。照合用の SHA-256 と、人が見分けるための先頭8文字だけを持つ。"""

    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_prefix", "prefix"),  # 照合はまず先頭8文字で候補を絞る
        Index("ix_api_keys_user_id", "user_id"),  # 自分のキーの一覧
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(16), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(String(50))
    prefix: Mapped[str] = mapped_column(String(8))
    key_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 の16進64桁
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 注入した Clock の時刻を入れる
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # この時刻から使えない
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 失効させた時刻


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_id_updated_at", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(16), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_id_seq"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        CheckConstraint("status IN ('complete', 'partial')", name="ck_messages_status"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey(f"{SCHEMA}.conversations.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="complete", server_default="complete")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
