"""ユーザー・API キー・課金計測の台帳（usage_events）の ORM モデル（スキーマ s13）。

users と api_keys は session09/models.py のコピー。テーブルは Alembic（src/session13/migrations）で作る。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import uuid_utils
from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, MetaData, Numeric, String,
                        UniqueConstraint, Uuid, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .providers import Usage

SCHEMA = "s13"


def new_id() -> str:
    """UUIDv7 を文字列で返す。"""
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
    __table_args__ = (
        Index("ix_api_keys_prefix", "prefix"),
        Index("ix_api_keys_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(16), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(String(50))
    prefix: Mapped[str] = mapped_column(String(8))
    key_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageEvent(Base):
    """課金計測の台帳。上流が 200 で応じた要求1つにつき1行（request_id が一意）。

    金額は記録した時刻（started_at）に効いていた単価で計算する。表に無いモデルは cost_usd を NULL にして残す。
    users への外部キーは CASCADE にしない（利用者を消しても、課金の記録は消さない）。
    """

    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_usage_events_request_id"),
        Index("ix_usage_events_user_id_started_at", "user_id", "started_at"),
        CheckConstraint("usage_source IN ('upstream', 'estimated')", name="ck_usage_events_usage_source"),
        CheckConstraint("outcome IN ('completed', 'failed', 'client_disconnected', 'cancelled')",
                        name="ck_usage_events_outcome"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0 AND cache_creation_input_tokens >= 0"
                        " AND cache_read_input_tokens >= 0", name="ck_usage_events_tokens"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(String(40))
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
