"""この章の Redis の状態を見る・消す（api コンテナの /app で実行する）。

    docker compose exec api python -m src.session11.cli breakers   # 経路ごとのブレーカの状態
    docker compose exec api python -m src.session11.cli reset      # s11: で始まるキーをすべて消す
"""

from __future__ import annotations

import asyncio
import sys

from kondate.cache import make_redis

ROUTES = ("primary", "light", "openai")


async def breakers() -> None:
    redis = make_redis()
    try:
        for name in ROUTES:
            h = await redis.hgetall(f"s11:cb:{name}")
            print(f"{name:<8} state={h.get('state', 'closed'):<9} failures={h.get('failures', '0')}")
    finally:
        await redis.aclose()


async def reset() -> None:
    redis = make_redis()
    try:
        n = 0
        async for key in redis.scan_iter("s11:*"):
            n += await redis.delete(key)
    finally:
        await redis.aclose()
    print(f"s11: のキーを {n} 個消しました")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "breakers":
        asyncio.run(breakers())
    elif cmd == "reset":
        asyncio.run(reset())
    else:
        print("使い方: python -m src.session11.cli breakers|reset")
        sys.exit(2)
