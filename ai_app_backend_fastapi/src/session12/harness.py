"""verify.py と verify_practice.py が共有する検証用の小道具（名前が verify で始まらないので単独では実行されない）。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx2
import uvicorn
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text

from kondate.cache import make_redis
from kondate.clock import Clock
from kondate.db import SessionLocal, engine
from kondate.verifykit import check, sse_events

from . import keys
from .app import JobSettings, get_job_settings, get_redis
from .auth import get_clock
from .models import SCHEMA, Base
from .store import TERMINAL
from .users import seed_users

URL = "/api/jobs/plan-week"
PORT = 18712  # serve() で使う。ほかのセッションの検証と重ならない番号

# ログは画面に出さない（期待される出力に job_id や request_id を混ぜないため）
_root = logging.getLogger("kondate.session12")
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
    """s12 を作り直し、5人のユーザーを入れる（他のセッションのスキーマには触れない）。"""
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        await seed_users(s)
        await s.commit()


async def clear_redis(prefix: str = "s12:") -> None:
    redis = make_redis()
    try:
        async for key in redis.scan_iter(f"{prefix}*"):
            await redis.delete(key)
    finally:
        await redis.aclose()


async def issue(user_id: str, clock: Clock) -> str:
    async with SessionLocal() as s:
        issued = await keys.issue_key(s, user_id, now=clock.now())
        await s.commit()
    return issued.key


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def no_sleep(_: float) -> None:
    """1日分の処理時間を待たない sleep（worker を通さずに run_plan を試すとき）。"""


@asynccontextmanager
async def redis_client() -> AsyncIterator[Redis]:
    redis = make_redis()
    try:
        yield redis
    finally:
        await redis.aclose()


@asynccontextmanager
async def overrides(app: FastAPI, *, clock: Clock, settings: JobSettings) -> AsyncIterator[Redis]:
    """時計・ジョブの設定・Redis を差し替える（lifespan を動かさずにアプリを呼ぶため）。"""
    redis = make_redis()
    app.dependency_overrides[get_clock] = lambda: clock
    app.dependency_overrides[get_job_settings] = lambda: settings
    app.dependency_overrides[get_redis] = lambda: redis
    try:
        yield redis
    finally:
        app.dependency_overrides.clear()
        await redis.aclose()


@asynccontextmanager
async def client_for(app: FastAPI, *, clock: Clock,
                     settings: JobSettings) -> AsyncIterator[tuple[httpx2.AsyncClient, Redis]]:
    """同一プロセスで app を呼ぶクライアント（応答は送り終わってから受け取る）。"""
    async with overrides(app, clock=clock, settings=settings) as redis:
        transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
            yield client, redis


@asynccontextmanager
async def serve(app: FastAPI, port: int = PORT) -> AsyncIterator[str]:
    """本物の HTTP サーバ（uvicorn）を同じプロセスで起動する（SSE を届いた順に読む試験に使う）。"""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           lifespan="off"))
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            if task.done():
                task.result()
            await asyncio.sleep(0.05)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def submit(client: httpx2.AsyncClient, key: str, days: int = 7) -> str:
    r = await client.post(URL, json={"days": days}, headers=bearer(key))
    assert r.status_code == 202, (r.status_code, r.text)
    return r.json()["job_id"]


async def wait_job(client: httpx2.AsyncClient, job_id: str, key: str,
                   until: Callable[[dict], bool] = lambda j: j["status"] in TERMINAL,
                   timeout: float = 15.0) -> dict:
    """GET /api/jobs/{job_id} を until が真になるまで繰り返す。worker が動いていなければ timeout で失敗する。"""
    deadline = time.monotonic() + timeout
    while True:
        r = await client.get(f"/api/jobs/{job_id}", headers=bearer(key))
        assert r.status_code == 200, (r.status_code, r.text)
        job = r.json()
        if until(job):
            return job
        if time.monotonic() > deadline:
            raise AssertionError(f"{timeout} 秒待っても条件を満たしません（worker は動いていますか）: {job}")
        await asyncio.sleep(0.05)


async def read_sse(client: httpx2.AsyncClient, url: str, headers: dict[str, str]) -> list[dict]:
    """SSE を終わりまで読み、sse_events() の形（event・data・id）にする。"""
    lines: list[str] = []
    async with client.stream("GET", url, headers=headers) as r:
        assert r.status_code == 200, r.status_code
        assert r.headers["content-type"].split(";")[0] == "text/event-stream", r.headers["content-type"]
        async for line in r.aiter_lines():
            lines.append(line)
    return [e for e in sse_events([*lines, ""]) if e["event"]]
