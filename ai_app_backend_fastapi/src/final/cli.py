"""最終プロジェクトの管理コマンド（api コンテナの /app で実行する）。

    docker compose exec api python -m src.final.cli setup              … マイグレーション（head まで）と5人の登録
    docker compose exec api python -m src.final.cli issue u001         … API キーを発行する（平文はこの1回だけ表示）
    docker compose exec api python -m src.final.cli register-key u001 kd_…   … 決めたキーを登録する（開発用）
    docker compose exec api python -m src.final.cli reset-redis        … Redis の final: のキーを消す

register-key は②の接続用：②の .env の BACKEND_API_KEY と同じ値を①に登録すれば、毎回キーを写さずに済む。
本番では使わない（キーは issue で発行し、平文はその場でだけ表示する）。
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
from pathlib import Path

from kondate.cache import make_redis
from kondate.clock import SystemClock
from kondate.db import SessionLocal, engine

from . import keys

ROOT = Path(__file__).resolve().parents[2]


async def setup() -> None:
    subprocess.run(["alembic", "-c", "src/final/alembic.ini", "upgrade", "head"], cwd=ROOT, check=True)
    async with SessionLocal() as session:
        count = await keys.seed_users(session)
        await session.commit()
    print(f"スキーマ final を head まで更新し、ユーザーを {count} 件登録しました（登録済みの人は数えません）")


async def issue(user_id: str, key: str | None) -> None:
    async with SessionLocal() as session:
        now = SystemClock().now()
        issued = await (keys.register_key(session, user_id, key, now=now) if key
                        else keys.issue_key(session, user_id, now=now))
        await session.commit()
    print("API キーを登録しました。" if key else "API キーを発行しました。平文はこの1回しか表示しません。")
    print(f"  user_id : {user_id}")
    print(f"  prefix  : {issued.prefix}")
    if not key:
        print(f"  api_key : {issued.key}")


async def reset_redis() -> None:
    redis = make_redis()
    try:
        removed = 0
        async for k in redis.scan_iter("final:*"):
            removed += await redis.delete(k)
    finally:
        await redis.aclose()
    print(f"Redis の final: のキーを {removed} 件消しました")


async def main(args: argparse.Namespace) -> None:
    try:
        if args.command == "setup":
            await setup()
        elif args.command == "issue":
            await issue(args.user_id, None)
        elif args.command == "register-key":
            await issue(args.user_id, args.key)
        else:
            await reset_redis()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m src.final.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="マイグレーションを head まで当て、data/users.json の5人を登録する")
    p = sub.add_parser("issue", help="API キーを1本発行する")
    p.add_argument("user_id")
    p = sub.add_parser("register-key", help="決めた API キー（kd_ に続く43文字）を登録する。開発用")
    p.add_argument("user_id")
    p.add_argument("key")
    sub.add_parser("reset-redis", help="Redis の final: のキー（回数・使用量・ブレーカ・ジョブ）を消す")
    asyncio.run(main(parser.parse_args()))
