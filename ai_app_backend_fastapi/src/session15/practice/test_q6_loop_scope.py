"""後半・練習問題6の解答：Redis のクライアントをモジュールで1つにし、テストも同じイベントループで動かす。

壊れていた版：@pytest_asyncio.fixture(scope="module") だけで loop_scope を書かず、テストは関数ごとのループで動いていた。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from kondate.cache import make_redis

pytestmark = pytest.mark.asyncio(loop_scope="module")  # このファイルのテストは、モジュールに1つのループで動かす
KEY = "s15:q6:counter"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def shared_redis() -> AsyncIterator[Redis]:
    r = make_redis()
    try:
        yield r
    finally:
        await r.aclose()


@pytest_asyncio.fixture(loop_scope="module")  # 作り直すのはテストごと（scope=function）、ループはモジュールのもの
async def counter(shared_redis: Redis) -> AsyncIterator[Redis]:
    await shared_redis.delete(KEY)
    yield shared_redis
    await shared_redis.delete(KEY)


async def test_first_increment(counter: Redis) -> None:
    assert await counter.incr(KEY) == 1


async def test_second_increment_starts_from_zero(counter: Redis) -> None:
    assert await counter.incr(KEY) == 1  # 前のテストの値が残っていない
