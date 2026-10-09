"""verify.py が使う検証用の小道具（名前が verify で始まらないので単独では実行されない）。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx2
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text

from kondate.cache import make_redis
from kondate.clock import Clock, FixedClock
from kondate.db import SessionLocal, engine
from kondate.settings import get_settings
from kondate.verifykit import check, sse_events

from . import keys
from .app import JobSettings, get_enqueue, get_job_settings
from .auth import get_clock
from .fallback import ResilientLLM, Route
from .models import SCHEMA, Base
from .plans import LimitSettings
from .providers import FakeProvider
from .ratelimit import get_limit_settings, get_redis
from .retry import FakeSleep
from .users import seed_users

URL = "/api/jobs/plan-week"
PREFIX = "review03:"

# ログは画面に出さない（期待される出力に job_id や request_id を混ぜないため）
_root = logging.getLogger("kondate.review03")
_root.propagate = False
_root.setLevel(logging.INFO)
_root.addHandler(logging.NullHandler())


def dbcheck(name: str) -> Callable[[Callable[[], Awaitable[object]]], None]:
    """async の check。終わるたびに接続プールを捨てる（check ごとに別のイベントループで動くため）。"""
    def deco(fn: Callable[[], Awaitable[object]]) -> None:
        async def wrapped() -> object:
            try:
                return await fn()
            finally:
                await engine.dispose()
        check(name)(wrapped)
    return deco


async def prepare_db() -> None:
    """review03 を作り直し、5人のユーザーを入れる（他のスキーマには触れない）。"""
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        await seed_users(s)
        await s.commit()


async def clear_redis(prefix: str = PREFIX) -> None:
    redis = make_redis()
    try:
        async for key in redis.scan_iter(f"{prefix}*"):
            await redis.delete(key)
    finally:
        await redis.aclose()


async def issue(user_id: str, clock: Clock) -> keys.IssuedKey:
    async with SessionLocal() as s:
        issued = await keys.issue_key(s, user_id, now=clock.now())
        await s.commit()
    return issued


async def revoke(user_id: str, key_id: str, clock: Clock) -> None:
    async with SessionLocal() as s:
        assert await keys.revoke_key(s, user_id, key_id, now=clock.now())
        await s.commit()


async def rotate(user_id: str, key_id: str, clock: Clock, grace: timedelta) -> keys.IssuedKey:
    async with SessionLocal() as s:
        new = await keys.rotate_key(s, user_id, key_id, now=clock.now(), grace=grace)
        await s.commit()
    assert new is not None
    return new


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@asynccontextmanager
async def redis_client() -> AsyncIterator[Redis]:
    redis = make_redis()
    try:
        yield redis
    finally:
        await redis.aclose()


@asynccontextmanager
async def client_for(app: FastAPI, *, clock: Clock, enqueued: list[str],
                     limit_settings: LimitSettings | None = None) -> AsyncIterator[tuple[httpx2.AsyncClient, Redis]]:
    """同一プロセスで app を呼ぶクライアント。積んだ job_id は enqueued に記録する（worker には送らない）。"""
    redis = make_redis()
    limits = limit_settings or LimitSettings()
    settings = JobSettings()

    async def record(job_id: str) -> None:
        enqueued.append(job_id)

    app.dependency_overrides[get_clock] = lambda: clock
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_enqueue] = lambda: record
    app.dependency_overrides[get_job_settings] = lambda: settings
    app.dependency_overrides[get_limit_settings] = lambda: limits
    try:
        transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
            yield client, redis
    finally:
        app.dependency_overrides.clear()
        await redis.aclose()


def make_llm(redis: Redis, clock: FixedClock, primary: FakeProvider,
             light: FakeProvider) -> tuple[ResilientLLM, FakeSleep]:
    """primary → light の2経路（各2回まで）。待ちは FakeSleep、ジッタは上限（rand=1.0）に固定する。"""
    sleep = FakeSleep(clock)
    routes = [Route("primary", primary), Route("light", light, get_settings().llm_model_light)]
    return ResilientLLM(routes, redis=redis, clock=clock, sleep=sleep, rand=lambda: 1.0), sleep


async def read_sse(client: httpx2.AsyncClient, url: str, headers: dict[str, str]) -> list[dict]:
    """SSE を終わりまで読み、sse_events() の形（event・data・id）にする。"""
    lines: list[str] = []
    async with client.stream("GET", url, headers=headers) as r:
        assert r.status_code == 200, r.status_code
        assert r.headers["content-type"].split(";")[0] == "text/event-stream", r.headers["content-type"]
        async for line in r.aiter_lines():
            lines.append(line)
    return [e for e in sse_events([*lines, ""]) if e["event"]]
