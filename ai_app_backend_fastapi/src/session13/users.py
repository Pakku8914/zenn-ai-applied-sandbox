"""data/users.json の5人を s13.users に入れる（session09/users.py のコピー。何度実行しても重複しない）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kondate.data import load_users

from .models import User


async def seed_users(session: AsyncSession) -> int:
    rows = [{"id": u["id"], "name": u["name"], "plan": u["plan"],
             "created_at": datetime.fromisoformat(u["created_at"])} for u in load_users()]
    inserted = await session.scalars(
        insert(User).values(rows).on_conflict_do_nothing(index_elements=["id"]).returning(User.id))
    return len(list(inserted))
