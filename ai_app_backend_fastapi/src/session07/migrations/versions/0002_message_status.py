"""発言に status 列を足す（途中で失敗した応答を partial として残すため）

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

SCHEMA = "s07"


def upgrade() -> None:
    # 既存の行があっても NOT NULL にできるよう、既定値を付けて足す
    op.add_column("messages", sa.Column("status", sa.String(16), nullable=False, server_default="complete"),
                  schema=SCHEMA)
    op.create_check_constraint("ck_messages_status", "messages", "status IN ('complete', 'partial')",
                               schema=SCHEMA)


def downgrade() -> None:
    op.drop_constraint("ck_messages_status", "messages", type_="check", schema=SCHEMA)
    op.drop_column("messages", "status", schema=SCHEMA)
