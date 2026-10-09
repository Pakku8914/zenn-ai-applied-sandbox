"""ユーザーと API キーの ORM モデル（session12/models.py のコピー。スキーマ review03）。

復習なので、テーブルは検証の冒頭（harness.prepare_db の create_all）で作る。
"""

from __future__ import annotations

from datetime import datetime

import uuid_utils
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, MetaData, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "review03"


def new_id() -> str:
    """UUIDv7 を文字列で返す。"""
    return str(uuid_utils.uuid7())


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)  # この章のテーブルはすべてスキーマ review03 に置く


class User(Base):
    """data/users.json の利用者。"""

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
