"""最終プロジェクトの ORM モデル（スキーマ final）。テーブルは Alembic（src/final/migrations）で作る。

- users・api_keys … session09／13 のコピー
- conversations・messages … mid01 のコピーに、持ち主（users への外部キー）と chat_id を足したもの
    chat_id は AI SDK の chatId（POST /api/chat の本文の id）。利用者ごとに一意で、API ではこれを会話の ID として見せる
    主キー（UUIDv7）は外に出さない
- usage_events … session13 のコピー。一意キーを turn_id（自前で採番した assistant の ID）に変え、
    受け取った x-request-id は相関用の request_id 列に残す（一意にしない）
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import uuid_utils
from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, MetaData, Numeric, String,
                        UniqueConstraint, Uuid, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .providers import Usage

SCHEMA = "final"


def new_id() -> str:
    return str(uuid_utils.uuid7())


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("plan IN ('free', 'pro')", name="ck_users_plan"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    plan: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_prefix", "prefix"), Index("ix_api_keys_user_id", "user_id"))

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(16), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(String(50))
    prefix: Mapped[str] = mapped_column(String(8))
    key_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("user_id", "chat_id", name="uq_conversations_user_id_chat_id"),
        Index("ix_conversations_user_id_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(16), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    chat_id: Mapped[str] = mapped_column(String(64))
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
    stop_reason: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageEvent(Base):
    """課金計測の台帳。往復1回につき1行（turn_id が一意）。"""

    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint("turn_id", name="uq_usage_events_turn_id"),
        Index("ix_usage_events_user_id_started_at", "user_id", "started_at"),
        Index("ix_usage_events_request_id", "request_id"),
        CheckConstraint("usage_source IN ('upstream', 'estimated')", name="ck_usage_events_usage_source"),
        CheckConstraint("outcome IN ('completed', 'failed', 'cancelled', 'rejected')",
                        name="ck_usage_events_outcome"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0 AND cache_creation_input_tokens >= 0"
                        " AND cache_read_input_tokens >= 0", name="ck_usage_events_tokens"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    turn_id: Mapped[str] = mapped_column(String(40))  # 自前で採番した ID（＝start の messageId）
    request_id: Mapped[str] = mapped_column(String(40))  # x-request-id（受け取ったもの・採番したもの）。相関用
    user_id: Mapped[str] = mapped_column(String(16), ForeignKey(f"{SCHEMA}.users.id"))
    model: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cache_creation_input_tokens: Mapped[int] = mapped_column(Integer)
    cache_read_input_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    price_from: Mapped[date | None] = mapped_column(Date)
    usage_source: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def usage(self) -> Usage:
        return Usage(self.input_tokens, self.output_tokens, self.cache_read_input_tokens,
                     self.cache_creation_input_tokens)
