"""最初のキーを作るための管理コマンド（API はキーが無いと呼べないので、最初の1本はここで発行する）。

    docker compose exec api python -m src.session09.cli seed-users
    docker compose exec api python -m src.session09.cli issue u001 --name ノートPC [--days 90]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from kondate.clock import SystemClock
from kondate.db import SessionLocal, engine

from . import keys
from .users import seed_users


async def main(args: argparse.Namespace) -> None:
    try:
        async with SessionLocal() as session:
            if args.command == "seed-users":
                print(f"ユーザーを {await seed_users(session)} 件登録しました")
            else:
                ttl = timedelta(days=args.days) if args.days else None
                issued = await keys.issue_key(session, args.user_id, now=SystemClock().now(),
                                              name=args.name, ttl=ttl)
                print("API キーを発行しました。平文はこの1回しか表示しません。いま安全な場所に控えてください。")
                print(f"  user_id : {args.user_id}")
                print(f"  key_id  : {issued.id}")
                print(f"  prefix  : {issued.prefix}")
                print(f"  api_key : {issued.key}")
            await session.commit()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m src.session09.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-users", help="data/users.json の5人を登録する")
    p = sub.add_parser("issue", help="API キーを1本発行する")
    p.add_argument("user_id")
    p.add_argument("--name", default=None)
    p.add_argument("--days", type=int, default=None, help="有効期限（日）。省略すると期限なし")
    asyncio.run(main(parser.parse_args()))
