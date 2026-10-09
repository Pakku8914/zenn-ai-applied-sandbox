"""DB セッションの依存性（session09/deps.py のコピーに、ストリームの中で使う工場 FactoryDep を足したもの）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kondate.db import SessionLocal


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """セッションを作る工場。ストリームの後始末（台帳への記録）は、この工場で自分のセッションを開いて行う。"""
    return SessionLocal


async def get_session(
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
FactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
