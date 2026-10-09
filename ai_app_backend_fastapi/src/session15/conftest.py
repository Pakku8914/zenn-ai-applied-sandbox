"""Session 15 のテストの設定。全セッション共通の pytest.ini は変えず、このディレクトリの中で閉じる。

pytest.ini（変えない）：asyncio_mode = auto ／ asyncio_default_fixture_loop_scope = function
- async のテストとフィクスチャは、印を付けなくても pytest-asyncio が動かす（auto）
- 何も指定しなければ、テストもフィクスチャも「テストごとに新しいイベントループ」で動く
- DB のスキーマ作成だけはセッションに1回（scope と loop_scope を session に）。中身はテストごとに空にする
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from kondate.cache import make_redis
from kondate.clock import FixedClock
from kondate.settings import get_settings

from .app import app
from .store import REDIS_PREFIX, SCHEMA, MemoryStore, SqlStore, create_tables
from .testkit import reset_mock


def pytest_configure(config: pytest.Config) -> None:
    # 登録しないと PytestUnknownMarkWarning になる（pytest.ini は共通なので、ここで足す）
    config.addinivalue_line("markers", "live: 実 API に接続する任意の確認（課金あり）。RUN_LIVE=1 のときだけ動く")


# ---------------------------------------------------------------- 外部に触れないもの（単体の層）


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()  # 2026-10-02 18:00 JST で止まった時計


@pytest.fixture
def memory_store(clock: FixedClock) -> MemoryStore:
    return MemoryStore(clock)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()  # テストが途中で落ちても、差し替えを次のテストへ持ち越さない


# ---------------------------------------------------------------- PostgreSQL・Redis・mockllm（結合の層）


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def schema() -> None:
    """スキーマ s15 を、テストのセッションの最初に1回だけ作り直す（テストごとに作ると遅い）。"""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        await create_tables(engine, drop_first=True)
    finally:
        await engine.dispose()  # このエンジンはセッションのループのもの。テストには渡さない


@pytest.fixture
async def db(schema: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """テストごとに表を空にし、このテストのイベントループで使うセッションの工場を渡す。"""
    # NullPool：接続をプールに残さない。ループの違うテストに接続を持ち越すと、別のループの接続を使ってしまう
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {SCHEMA}.chat_turns"))  # 後片付けではなく前片付け
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    """テストごとに s15: のキーだけを消す（FLUSHDB は他のセッションのキーまで消すので使わない）。"""
    r = make_redis()
    keys = [k async for k in r.scan_iter(match=f"{REDIS_PREFIX}*")]
    if keys:
        await r.delete(*keys)
    try:
        yield r
    finally:
        await r.aclose()


@pytest.fixture
def sql_store(db: async_sessionmaker[AsyncSession], redis: Redis, clock: FixedClock) -> SqlStore:
    return SqlStore(db, redis, clock)


@pytest.fixture
async def mock() -> None:
    """mockllm の統計と障害注入の回数を消す（テストの先頭で。並べて流すと数が混ざる）。"""
    await reset_mock()
