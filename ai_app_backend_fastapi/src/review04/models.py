"""課金計測の台帳 usage_events（session13/models.py から UsageEvent だけをコピー。スキーマ review04）。

復習なので Alembic は使わず、検証スクリプトが create_all で作る。users の表は置かないので、users への外部キーも外している
（最終プロジェクトでは session13 と同じく users を参照し、CASCADE にしない）。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import uuid_utils
from sqlalchemy import CheckConstraint, Date, DateTime, Index, Integer, MetaData, Numeric, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .providers import Usage

SCHEMA = "review04"


def new_id() -> str:
    return str(uuid_utils.uuid7())


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class UsageEvent(Base):
    """上流が 200 で応じた要求1つにつき1行（request_id が一意）。"""

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
    user_id: Mapped[str] = mapped_column(String(16))
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
