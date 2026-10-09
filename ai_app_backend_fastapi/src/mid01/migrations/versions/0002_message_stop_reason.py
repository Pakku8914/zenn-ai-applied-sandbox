"""発言に stop_reason 列を足す（ステップ上限で止めた往復を、ふつうの終わり方と区別するため）

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

SCHEMA = "mid01"


def upgrade() -> None:
    # NULL を許す列なので、既存の行があってもそのまま足せる（user の発言と partial は NULL のまま）
    op.add_column("messages", sa.Column("stop_reason", sa.String(16), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("messages", "stop_reason", schema=SCHEMA)
