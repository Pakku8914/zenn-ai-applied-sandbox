"""verify.py と verify_practice.py が共有する検証用の小道具（名前が verify で始まらないので単独では実行されない）。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text

from kondate.cache import make_redis
from kondate.clock import Clock
from kondate.db import SessionLocal, engine
from kondate.settings import get_settings
from kondate.verifykit import check

from . import keys
from .app import get_provider
from .auth import get_clock
from .limiter import Limiter, QuotaState
from .models import SCHEMA, Base
from .plans import PlanLimits
from .providers import ChatRequest, ChatResult, LLMProvider, StreamEvent, open_provider
from .ratelimit import get_redis
from .users import seed_users

PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"  # 入力の見積もり 34 トークン
FAKE_TEXT = "鶏むね肉とキャベツの塩炒めがおすすめです。"  # 21文字 → 6文字ずつ4つの delta

# ログは画面に出さない（期待される出力に request_id などを混ぜないため）
_root = logging.getLogger("kondate.session10")
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
    """s10 を作り直し、5人のユーザーを入れる（他のセッションのスキーマには触れない）。"""
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        await seed_users(s)
        await s.commit()


async def clear_redis(prefix: str = "s10:") -> None:
    """Redis の s10: で始まるキーだけを消す。"""
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


@asynccontextmanager
async def redis_client() -> AsyncIterator[Redis]:
    redis = make_redis()
    try:
        yield redis
    finally:
        await redis.aclose()


@asynccontextmanager
async def client_for(app: FastAPI, *, clock: Clock,
                     provider: LLMProvider) -> AsyncIterator[tuple[httpx2.AsyncClient, Redis]]:
    """同一プロセスで app を呼ぶクライアント。時計・上流・Redis を差し替える（lifespan は動かない）。"""
    redis = make_redis()
    app.dependency_overrides[get_clock] = lambda: clock
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_redis] = lambda: redis
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
            yield client, redis
    finally:
        app.dependency_overrides.clear()
        await redis.aclose()


@asynccontextmanager
async def mock_provider(headers: dict[str, str] | None = None) -> AsyncIterator[LLMProvider]:
    """接続先を必ず mockllm に向けた Anthropic のプロバイダ（SDK の自動リトライなし）。"""
    s = get_settings()
    async with open_provider("anthropic", model=s.llm_model, base_url=s.mockllm_url, api_key="mock-key",
                             max_retries=0, timeout=30.0, default_headers=headers) as provider:
        yield provider


class CountingProvider:
    """上流を何回呼んだかを数える包み（自前の待ち時間で、上流を呼ばずに済んだかを確かめる）。"""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner, self.name = inner, inner.name
        self.calls = 0

    async def complete(self, req: ChatRequest) -> ChatResult:
        self.calls += 1
        return await self.inner.complete(req)

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        async for ev in self.inner.stream(req):
            yield ev


class Connected:
    """relay_chat に渡す要求の代わり（切断されていない）。ストリームの途中で閉じる試験に使う。"""

    async def is_disconnected(self) -> bool:
        return False


async def settled_state(limiter: Limiter, user_id: str, limits: PlanLimits, clock: Clock,
                        timeout: float = 3.0) -> QuotaState:
    """予約が精算されるまで待ってから、その日の状態を返す（ストリームの後始末は応答の直後に走るため）。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        state = await limiter.quota_state(user_id, limits, clock.now())
        if state.reserved == 0 or loop.time() > deadline:
            return state
        await asyncio.sleep(0.05)
