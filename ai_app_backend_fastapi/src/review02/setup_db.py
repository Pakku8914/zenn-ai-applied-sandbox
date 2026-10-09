"""復習2のテーブルを作り直す（スキーマ review02 だけを消して作る。他のスキーマには触れない）。

    docker compose exec api python src/review02/setup_db.py
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from kondate.db import engine
from src.review02.models import SCHEMA, Base


async def reset_schema() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)  # 復習なので create_all。本番の変更管理は Alembic（セッション7）


async def main() -> None:
    try:
        await reset_schema()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
    print(f"スキーマ {SCHEMA} を作り直しました")
