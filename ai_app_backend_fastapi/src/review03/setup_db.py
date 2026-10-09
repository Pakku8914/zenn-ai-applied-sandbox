"""復習3のテーブルを作り直し、5人の利用者を入れる（スキーマ review03 と Redis の review03: だけを消す）。

    docker compose exec api python src/review03/setup_db.py
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from kondate.cache import make_redis
from kondate.db import SessionLocal, engine
from src.review03.models import SCHEMA, Base
from src.review03.users import seed_users

PREFIX = "review03:"


async def reset_schema() -> int:
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)  # 復習なので create_all。本番の変更管理は Alembic（セッション7）
    async with SessionLocal() as session:
        count = await seed_users(session)
        await session.commit()
    return count


async def clear_redis() -> None:
    redis = make_redis()
    try:
        async for key in redis.scan_iter(f"{PREFIX}*"):  # ジョブの記録・枠・冪等キーなど、前回の残りを消す
            await redis.delete(key)
    finally:
        await redis.aclose()


async def main() -> int:
    try:
        count = await reset_schema()
        await clear_redis()
    finally:
        await engine.dispose()
    return count


if __name__ == "__main__":
    count = asyncio.run(main())
    print(f"スキーマ {SCHEMA} を作り直し、ユーザーを {count} 件登録しました（Redis の {PREFIX} のキーも消しました）")
