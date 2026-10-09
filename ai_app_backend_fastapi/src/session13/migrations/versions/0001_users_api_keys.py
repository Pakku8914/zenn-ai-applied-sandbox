"""ユーザーと API キーのテーブルを作る（session09 の 0001・0002 から users と api_keys だけ）

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "s13"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("plan", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("plan IN ('free', 'pro')", name="ck_users_plan"),
        schema=SCHEMA,
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("user_id", sa.String(16), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("name", sa.String(50), nullable=True),
        sa.Column("prefix", sa.String(8), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"], schema=SCHEMA)
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_api_keys_user_id", table_name="api_keys", schema=SCHEMA)
    op.drop_index("ix_api_keys_prefix", table_name="api_keys", schema=SCHEMA)
    op.drop_table("api_keys", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
