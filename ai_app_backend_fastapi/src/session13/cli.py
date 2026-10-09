"""Session 13 の管理コマンド（api コンテナの /app で実行する。先に alembic upgrade head を済ませる）。

    docker compose exec api python -m src.session13.cli seed-users     … data/users.json の5人を登録する
    docker compose exec api python -m src.session13.cli issue u001     … API キーを発行する（平文はこの1回だけ表示）
    docker compose exec api python -m src.session13.cli reset-limits   … Redis の s13: のキーを消す
    docker compose exec api python -m src.session13.cli recompute      … 台帳の金額を、いまの単価表で計算し直す
"""

from __future__ import annotations

import argparse
import asyncio

from kondate.cache import make_redis
from kondate.clock import SystemClock
from kondate.db import SessionLocal, engine

from . import keys
from .metering import recompute_costs
from .models import SCHEMA
from .pricing import load_price_table
from .users import seed_users


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
        if args.command == "reset-limits":
            await reset_limits()
            return
        async with SessionLocal() as session:
            if args.command == "seed-users":
                print(f"ユーザーを {await seed_users(session)} 件登録しました")
            elif args.command == "recompute":
                print(f"金額を計算し直しました：{await recompute_costs(session, load_price_table())} 行が変わりました")
            else:
                issued = await keys.issue_key(session, args.user_id, now=SystemClock().now())
                print("API キーを発行しました。平文はこの1回しか表示しません。")
                print(f"  user_id : {args.user_id}")
                print(f"  api_key : {issued.key}")
            await session.commit()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m src.session13.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-users", help="data/users.json の5人を登録する")
    p = sub.add_parser("issue", help="API キーを1本発行する")
    p.add_argument("user_id")
    sub.add_parser("reset-limits", help="Redis の s13: のキー（回数・使用量・上流の待ち時間）を消す")
    sub.add_parser("recompute", help="usage_events の金額を、各行の時刻に効いていた単価で計算し直す")
    asyncio.run(main(parser.parse_args()))
