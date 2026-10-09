"""PostgreSQL への非同期接続（SQLAlchemy 2.1 async + asyncpg）。"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from kondate.settings import get_settings

engine: AsyncEngine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def server_version() -> str:
    async with engine.connect() as conn:
        return (await conn.execute(text("SHOW server_version"))).scalar_one()
