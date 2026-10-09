"""練習問題4の解答：漏えいに気づいたときの一括失効（いま使っているキーだけは残せる）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ApiKey


async def revoke_all(session: AsyncSession, user_id: str, *, now: datetime, keep_key_id: str | None = None) -> int:
    """user_id のまだ失効していないキーをすべて失効させ、その本数を返す。commit は呼び出し側。"""
    stmt = (update(ApiKey)
            .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
            .values(revoked_at=now)
            .returning(ApiKey.id))
    if keep_key_id is not None:
        stmt = stmt.where(ApiKey.id != keep_key_id)
    return len(list(await session.scalars(stmt)))
