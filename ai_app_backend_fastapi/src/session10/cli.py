"""Session 10 の準備コマンド（api コンテナの /app で実行する）。

    docker compose exec api python -m src.session10.cli setup          … スキーマ s10 を作り直し、5人を登録する
    docker compose exec api python -m src.session10.cli issue u001     … API キーを発行する（平文はこの1回だけ表示）
    docker compose exec api python -m src.session10.cli reset-limits   … Redis の s10: のキーを消す
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from kondate.cache import make_redis
from kondate.clock import SystemClock
from kondate.db import SessionLocal, engine

from . import keys
from .models import SCHEMA, Base
from .users import seed_users


async def setup() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        count = await seed_users(session)
        await session.commit()
    print(f"スキーマ {SCHEMA} を作り直し、ユーザーを {count} 件登録しました")


async def issue(user_id: str) -> None:
    async with SessionLocal() as session:
        issued = await keys.issue_key(session, user_id, now=SystemClock().now())
        await session.commit()
    print("API キーを発行しました。平文はこの1回しか表示しません。")
    print(f"  user_id : {user_id}")
    print(f"  api_key : {issued.key}")


async def reset_limits() -> None:
    redis = make_redis()
    try:
        removed = 0
        async for key in redis.scan_iter(f"{SCHEMA}:*"):
            removed += await redis.delete(key)
    finally:
        await redis.aclose()
    print(f"Redis の {SCHEMA}: のキーを {removed} 件消しました")


async def main(args: argparse.Namespace) -> None:
    try:
        if args.command == "setup":
            await setup()
        elif args.command == "issue":
            await issue(args.user_id)
        else:
            await reset_limits()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m src.session10.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="スキーマ s10 を作り直し、data/users.json の5人を登録する")
    p = sub.add_parser("issue", help="API キーを1本発行する")
    p.add_argument("user_id")
    sub.add_parser("reset-limits", help="Redis の s10: のキー（回数・使用量・上流の待ち時間）を消す")
    asyncio.run(main(parser.parse_args()))
