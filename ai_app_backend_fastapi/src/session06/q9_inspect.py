"""後半の練習問題2：保存したイベントの状態を調べる（再送が 204 になる理由を切り分ける）。

    docker compose exec api python -m src.session06.q9_inspect <message_id>
"""

from __future__ import annotations

import asyncio
import json
import sys

from redis.asyncio import Redis

from kondate.cache import make_redis

from .resume import TERMINAL, TTL_SECONDS, events_key


async def inspect_log(redis: Redis, message_id: str) -> dict:
    key = events_key(message_id)
    raw = await redis.lrange(key, 0, -1)
    ttl = await redis.ttl(key)  # キーが無ければ -2、期限が無ければ -1
    last = json.loads(raw[-1])["event"] if raw else None
    return {"count": len(raw), "last_event": last, "replayable": last in TERMINAL,
            "ttl_ok": 0 < ttl <= TTL_SECONDS}


async def main(message_id: str) -> None:
    redis = make_redis()
    try:
        print(await inspect_log(redis, message_id))
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
