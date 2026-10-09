"""DB セッションの依存性（session09/deps.py のコピー）。1リクエストに1つの AsyncSession を作り、終わったら必ず閉じる。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kondate.db import SessionLocal


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return SessionLocal


async def get_session(
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
