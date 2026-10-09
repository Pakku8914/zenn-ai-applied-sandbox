"""結合の層：本物の SDK → mockllm、本物の PostgreSQL・Redis。異常は mockllm のヘッダで注入する。"""

from __future__ import annotations

from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..store import ChatTurn, SqlStore
from ..testkit import chat_via_mock, mock_stats

pytestmark = pytest.mark.usefixtures("mock")  # どのテストも、先頭で mockllm の統計と回数を消す
USAGE_KEY = "s15:usage:20261002"  # FixedClock の日付


async def saved_rows(db: async_sessionmaker[AsyncSession]) -> list[ChatTurn]:
    async with db() as session:
        return list((await session.scalars(select(ChatTurn))).all())


async def test_success_is_saved(sql_store: SqlStore, db: async_sessionmaker[AsyncSession], redis: Redis) -> None:
    run = await chat_via_mock(None, sql_store)
    assert run.shape() == "start → delta×32 → usage → done"
    rows = await saved_rows(db)
    assert [(r.input_tokens, r.output_tokens, len(r.answer)) for r in rows] == [(34, 181, 192)]
    assert rows[0].id == run.data_of("start")[0]["message_id"]
    assert await redis.hgetall(USAGE_KEY) == {"turns": "1", "input_tokens": "34", "output_tokens": "181"}
    stats = await mock_stats()
    assert (stats["total"], stats["by_status"]) == (1, {"200": 1})


@pytest.mark.parametrize(("fault", "status", "type_"), [
    ("429", 429, "rate_limited"),
    ("529", 503, "upstream_unavailable"),
    ("500", 503, "upstream_unavailable"),
])
async def test_prestart_fault(fault: str, status: int, type_: str, sql_store: SqlStore,
                              db: async_sessionmaker[AsyncSession]) -> None:
    run = await chat_via_mock({"x-mock-fault": fault}, sql_store)
    assert (run.status, run.body["error"]["type"]) == (status, type_)
    assert run.headers.get("retry-after") == ("1" if status == 429 else None)  # mockllm の retry-after をそのまま
    assert await saved_rows(db) == []
    assert (await mock_stats())["by_status"] == {fault: 1}  # max_retries=0：SDK は送り直していない


@pytest.mark.parametrize(("fault", "type_"), [
    ("sse-error", "upstream_error"),
    ("disconnect", "upstream_unavailable"),
])
async def test_midstream_fault(fault: str, type_: str, sql_store: SqlStore,
                               db: async_sessionmaker[AsyncSession], redis: Redis) -> None:
    run = await chat_via_mock({"x-mock-fault": fault}, sql_store)
    assert (run.status, run.shape()) == (200, "start → delta×2 → error")
    assert run.data_of("error")[0]["type"] == type_
    assert await saved_rows(db) == []
    assert await redis.hgetall(USAGE_KEY) == {}


async def test_fault_times_then_recovers(sql_store: SqlStore, db: async_sessionmaker[AsyncSession]) -> None:
    # 回数を数える単位（key）をテストごとに変える。既定の key は本文のハッシュなので、ほかのテストと混ざる
    headers = {"x-mock-fault": "429", "x-mock-fault-times": "1", "x-mock-fault-key": f"s15-{uuid4().hex}"}
    first = await chat_via_mock(headers, sql_store)
    second = await chat_via_mock(headers, sql_store)
    assert (first.status, second.status) == (429, 200)
    assert len(await saved_rows(db)) == 1
    assert (await mock_stats())["by_status"] == {"429": 1, "200": 1}
