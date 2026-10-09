"""練習問題7の解答：台帳（DB）に書けない間は Redis のリストに退避し、あとで流し込む。

流し込みは何度やり直しても安全（request_id が一意なので、同じ記録は二重に入らない）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .metering import UsageRecord, save_usage
from .pricing import PriceTable
from .providers import Usage

PENDING_KEY = "s13:usage:pending"
logger = logging.getLogger("kondate.session13.q7")


def to_json(record: UsageRecord) -> str:
    data = asdict(record)
    data["started_at"] = record.started_at.isoformat()
    return json.dumps(data, ensure_ascii=False)


def from_json(raw: str) -> UsageRecord:
    data = json.loads(raw)
    return UsageRecord(**{**data, "started_at": datetime.fromisoformat(data["started_at"]),
                          "usage": Usage(**data["usage"])})


async def save_or_park(factory: async_sessionmaker[AsyncSession], redis: Redis, record: UsageRecord,
                       table: PriceTable) -> str:
    """"saved"・"duplicate"・"parked"（DB に書けなかったので退避した）のどれかを返す。"""
    try:
        return "saved" if await save_usage(factory, record, table) else "duplicate"
    except Exception:
        logger.warning("usage_record_parked request_id=%s", record.request_id)
        await redis.rpush(PENDING_KEY, to_json(record))
        return "parked"


async def flush_pending(factory: async_sessionmaker[AsyncSession], redis: Redis, table: PriceTable, *,
                        limit: int = 1000) -> tuple[int, int]:
    """退避した記録を古い順に台帳へ入れ、(新しく入った件数, もうあった件数) を返す。"""
    inserted = duplicates = 0
    for _ in range(limit):
        raw = await redis.lpop(PENDING_KEY)
        if raw is None:
            break
        try:
            saved = await save_usage(factory, from_json(raw), table)
        except Exception:
            await redis.lpush(PENDING_KEY, raw)  # 先頭に戻し、次の機会にやり直す（DB はまだ落ちている）
            raise
        if saved:
            inserted += 1
        else:
            duplicates += 1
    return inserted, duplicates
