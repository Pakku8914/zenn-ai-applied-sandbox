"""ユーザー・API キー・会話・発言・課金計測の台帳を作る（session13 と mid01 の表を1つにまとめたもの）

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "final"


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
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("user_id", sa.String(16), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "chat_id", name="uq_conversations_user_id_chat_id"),
        schema=SCHEMA,
    )
    op.create_index("ix_conversations_user_id_updated_at", "conversations", ["user_id", "updated_at"],
                    schema=SCHEMA)
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(as_uuid=False),
                  sa.ForeignKey(f"{SCHEMA}.conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="complete"),
        sa.Column("stop_reason", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_id_seq"),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        sa.CheckConstraint("status IN ('complete', 'partial')", name="ck_messages_status"),
        schema=SCHEMA,
    )
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("turn_id", sa.String(40), nullable=False),
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
        sa.UniqueConstraint("turn_id", name="uq_usage_events_turn_id"),
        sa.CheckConstraint("usage_source IN ('upstream', 'estimated')", name="ck_usage_events_usage_source"),
        sa.CheckConstraint("outcome IN ('completed', 'failed', 'cancelled', 'rejected')",
                           name="ck_usage_events_outcome"),
        sa.CheckConstraint("input_tokens >= 0 AND output_tokens >= 0 AND cache_creation_input_tokens >= 0"
                           " AND cache_read_input_tokens >= 0", name="ck_usage_events_tokens"),
        schema=SCHEMA,
    )
    op.create_index("ix_usage_events_user_id_started_at", "usage_events", ["user_id", "started_at"],
                    schema=SCHEMA)
    op.create_index("ix_usage_events_request_id", "usage_events", ["request_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("usage_events", schema=SCHEMA)
    op.drop_table("messages", schema=SCHEMA)
    op.drop_table("conversations", schema=SCHEMA)
    op.drop_table("api_keys", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
