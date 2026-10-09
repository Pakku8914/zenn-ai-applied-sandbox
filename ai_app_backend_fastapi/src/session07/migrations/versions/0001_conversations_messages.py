"""会話と発言のテーブルを作る

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

SCHEMA = "s07"


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("user_id", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
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
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_id_seq"),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("messages", schema=SCHEMA)
    op.drop_index("ix_conversations_user_id_updated_at", table_name="conversations", schema=SCHEMA)
    op.drop_table("conversations", schema=SCHEMA)
