"""フィクスチャの確認：同じテストを2回流しても、前の回の行やキーが残っていない。"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid_utils import uuid7

from ..store import ChatTurn, SqlStore, Turn


@pytest.mark.parametrize("round_", [1, 2])
async def test_each_test_starts_empty(round_: int, sql_store: SqlStore,
                                      db: async_sessionmaker[AsyncSession]) -> None:
    await sql_store.save_turn(Turn(str(uuid7()), f"req_iso_{round_}", "卵は何日もつ？", "冷蔵で2週間ほどです。", 10, 5))
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(ChatTurn)) == 1  # 2回目も 2 にならない
    assert await sql_store.usage_today() == {"date": "2026-10-02", "turns": 1, "input_tokens": 10, "output_tokens": 5}
