"""後半・練習問題3の解答：Redis の今日の使用量を、フィクスチャで初期化した状態から確かめる。"""

from __future__ import annotations

from redis.asyncio import Redis
from uuid_utils import uuid7

from ..store import USAGE_TTL, SqlStore, Turn

USAGE_KEY = "s15:usage:20261002"  # FixedClock の日付


async def test_usage_sums_two_turns(sql_store: SqlStore, redis: Redis) -> None:
    await sql_store.save_turn(Turn(str(uuid7()), "req_u1", "卵は何日もつ？", "冷蔵で2週間ほどです。", 10, 5))
    await sql_store.save_turn(Turn(str(uuid7()), "req_u2", "豆腐は冷凍できる？", "できます。", 20, 7))
    assert await sql_store.usage_today() == {"date": "2026-10-02", "turns": 2, "input_tokens": 30, "output_tokens": 12}
    assert 0 < await redis.ttl(USAGE_KEY) <= USAGE_TTL  # 写しには期限を付けている
    assert [k async for k in redis.scan_iter(match="s15:*")] == [USAGE_KEY]


async def test_next_test_starts_without_keys(redis: Redis) -> None:
    # 前のテストが s15:usage:20261002 を残していても、redis フィクスチャが先に消している
    assert [k async for k in redis.scan_iter(match="s15:*")] == []
