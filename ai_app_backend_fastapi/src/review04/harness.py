"""verify.py が使う検証用の小道具（名前が verify で始まらないので、単独では実行されない）。"""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal

import httpx2
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text

from kondate.cache import make_redis
from kondate.clock import FixedClock
from kondate.db import engine
from kondate.settings import get_settings
from kondate.verifykit import check, sse_events

from .app import get_clock, get_llm
from .breaker import PREFIX
from .fallback import ResilientLLM, Route
from .jsonlog import setup_json_logging
from .models import SCHEMA, Base
from .providers import ChatRequest, ChatResult, StreamEvent, TextDelta
from .q5_replay import half
from .retry import FakeSleep

BASE = get_settings()
CHAT = BASE.llm_model
LIGHT = BASE.llm_model_light


def usd(amount: Decimal | None) -> str | None:
    return None if amount is None else format(amount, "f")


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
    """スキーマ review04 を作り直して、usage_events を create_all で作る（他のスキーマには触れない）。"""
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)


async def clear_events() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"DELETE FROM {SCHEMA}.usage_events"))


async def rows(sql: str, **params: object) -> list[tuple]:
    async with engine.connect() as conn:
        return [tuple(r) for r in await conn.execute(text(sql), params)]


async def clear_redis() -> None:
    redis = make_redis()
    try:
        async for key in redis.scan_iter(f"{PREFIX}:*"):
            await redis.delete(key)
    finally:
        await redis.aclose()


@asynccontextmanager
async def redis_client() -> AsyncIterator[Redis]:
    redis = make_redis()
    try:
        yield redis
    finally:
        await redis.aclose()


async def reset_mock() -> None:
    async with httpx2.AsyncClient(timeout=5) as c:
        (await c.post(f"{BASE.mockllm_url}/_mock/reset")).raise_for_status()


async def mock_stats() -> dict:
    async with httpx2.AsyncClient(timeout=5) as c:
        r = await c.get(f"{BASE.mockllm_url}/_mock/stats")
        r.raise_for_status()
        return r.json()


class LogBuffer:
    """kondate.review04 の JSON ログを画面に出さずに貯める。"""

    def __init__(self) -> None:
        self.buf = io.StringIO()
        setup_json_logging("kondate.review04", stream=self.buf)

    def clear(self) -> None:
        self.buf.seek(0)
        self.buf.truncate()

    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self.buf.getvalue().splitlines() if line.strip()]

    def events(self, name: str) -> list[dict]:
        return [d for d in self.lines() if d["event"] == name]


class StallingProvider:
    """差分を送ったあと、Done を送らずに黙り続ける上流（長い応答の途中で止まったまま）。"""

    name = "stalling"

    def __init__(self, texts: Sequence[str]) -> None:
        self.texts = list(texts)

    async def complete(self, req: ChatRequest) -> ChatResult:
        raise NotImplementedError

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        for t in self.texts:
            yield TextDelta(t)
        await asyncio.Event().wait()  # 取り消されるまで返らない


class BrokenFactory:
    """async_sessionmaker の代わり。セッションを開こうとすると失敗する（DB が止まっている）。"""

    def __call__(self) -> BrokenFactory:
        return self

    async def __aenter__(self) -> None:
        raise ConnectionRefusedError("DB に接続できません（検証用）")

    async def __aexit__(self, *exc: object) -> bool:
        return False


@asynccontextmanager
async def client_for(app: FastAPI, routes: Sequence[Route], *, clock: FixedClock) -> AsyncIterator[httpx2.AsyncClient]:
    """同一プロセスで app を呼ぶクライアント。ResilientLLM（待ちは FakeSleep）と時計を差し替える。"""
    redis = make_redis()
    llm = ResilientLLM(routes, redis=redis, clock=clock, sleep=FakeSleep(clock), rand=half, prefix=PREFIX)
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_clock] = lambda: clock
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        await redis.aclose()


def sse_names(body: str) -> list[str | None]:
    return [e["event"] for e in sse_events([*body.splitlines(), ""])]


def shape(names: Sequence[str | None]) -> str:
    """["start", "delta", "delta", "done"] を「start → delta×2 → done」に縮める。"""
    runs: list[list] = []
    for n in names:
        label = n or ": ping"
        if runs and runs[-1][0] == label:
            runs[-1][1] += 1
        else:
            runs.append([label, 1])
    return " → ".join(k if c == 1 else f"{k}×{c}" for k, c in runs)
