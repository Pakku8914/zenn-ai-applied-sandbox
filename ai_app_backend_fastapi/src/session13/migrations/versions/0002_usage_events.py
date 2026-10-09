"""課金計測の台帳 usage_events を作る（request_id が一意・金額は NUMERIC(14, 8)）

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SCHEMA = "s13"


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("request_id", sa.String(40), nullable=False),
        # 利用者を消しても課金の記録は消さない（CASCADE にしない）
        sa.Column("user_id", sa.String(16), sa.ForeignKey(f"{SCHEMA}.users.id"), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(14, 8), nullable=True),
        sa.Column("price_from", sa.Date(), nullable=True),
        sa.Column("usage_source", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("request_id", name="uq_usage_events_request_id"),
        sa.CheckConstraint("usage_source IN ('upstream', 'estimated')", name="ck_usage_events_usage_source"),
        sa.CheckConstraint("outcome IN ('completed', 'failed', 'client_disconnected', 'cancelled')",
                           name="ck_usage_events_outcome"),
        sa.CheckConstraint("input_tokens >= 0 AND output_tokens >= 0 AND cache_creation_input_tokens >= 0"
                           " AND cache_read_input_tokens >= 0", name="ck_usage_events_tokens"),
        schema=SCHEMA,
    )
    op.create_index("ix_usage_events_user_id_started_at", "usage_events", ["user_id", "started_at"],
                    schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_usage_events_user_id_started_at", table_name="usage_events", schema=SCHEMA)
    op.drop_table("usage_events", schema=SCHEMA)
