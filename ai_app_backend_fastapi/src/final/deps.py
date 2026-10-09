"""DB セッションと時計の依存性（session13/deps.py・auth.py のコピー）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kondate.clock import Clock, SystemClock
from kondate.db import SessionLocal

SYSTEM_CLOCK = SystemClock()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """セッションを作る工場。ストリームの後始末（保存・台帳への記録）は、この工場で自分のセッションを開いて行う。"""
    return SessionLocal


async def get_session(
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session


def get_clock() -> Clock:
    """認証・レート制限・クォータ・予算・台帳の時刻・ジョブの ID を、この1つの時計で決める。"""
    return SYSTEM_CLOCK


SessionDep = Annotated[AsyncSession, Depends(get_session)]
FactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
ClockDep = Annotated[Clock, Depends(get_clock)]
