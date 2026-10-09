"""verify.py と verify_practice.py が共有する検証用の小道具（名前が verify で始まらないので単独では実行されない）。"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import httpx2
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text

from kondate.cache import make_redis
from kondate.clock import Clock
from kondate.db import SessionLocal, engine
from kondate.settings import get_settings
from kondate.verifykit import check, eq

from . import keys
from .app import get_provider
from .auth import get_clock
from .budget import BudgetSettings, get_budget_settings
from .inputs import get_model
from .models import SCHEMA
from .pricing import PriceTable, get_price_table
from .providers import ChatRequest, ChatResult, LLMProvider, StreamEvent, open_provider
from .ratelimit import get_redis
from .users import seed_users

ROOT = Path(__file__).resolve().parents[2]
INI = "src/session13/alembic.ini"
BASE = get_settings()
CHAT = BASE.llm_model  # チャット用のモデル（単価表のキー）
LIGHT = BASE.llm_model_light  # 軽い処理用のモデル
PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"  # 81バイト → 27 トークン（メッセージで 30）
FAKE_TEXT = "鶏むね肉とキャベツの塩炒めがおすすめです。"  # 21文字 → 6文字ずつ4つの delta
RULE = "献立は家にある食材を優先し、調理時間と栄養の釣り合いを考えて提案します。"  # 36文字・108バイト → 36 トークン
CACHE_SYSTEM = RULE * 30  # 1080 トークン。接頭辞は 4＋1080＝1084（1024 以上なのでキャッシュされる）
SHORT_SYSTEM = RULE * 10  # 360 トークン。接頭辞 364 ではキャッシュされない

# ログは画面に出さない（期待される出力に request_id などを混ぜないため）
_root = logging.getLogger("kondate.session13")
_root.propagate = False
_root.setLevel(logging.INFO)
_root.addHandler(logging.NullHandler())


def usd(amount: Decimal | None) -> str | None:
    """Decimal を指数表記なしの文字列にする（0E-8 や 2.0E-7 と書かせない）。"""
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


def alembic(*args: str) -> str:
    r = subprocess.run(["alembic", "-c", INI, *args], cwd=ROOT, capture_output=True, text=True)
    eq(r.returncode, 0, f"alembic {' '.join(args)}\n{r.stdout}{r.stderr}")
    return r.stdout + r.stderr


async def prepare_db() -> None:
    """s13 を消してマイグレーションを当て直し、5人のユーザーを入れる（他のセッションのスキーマには触れない）。"""
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
    await asyncio.to_thread(alembic, "upgrade", "head")
    async with SessionLocal() as s:
        await seed_users(s)
        await s.commit()


async def clear_events() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"DELETE FROM {SCHEMA}.usage_events"))


async def scalar(sql: str, **params: object) -> object:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()


async def rows(sql: str, **params: object) -> list[tuple]:
    async with engine.connect() as conn:
        return [tuple(r) for r in await conn.execute(text(sql), params)]


async def clear_redis(prefix: str = "s13:") -> None:
    redis = make_redis()
    try:
        async for key in redis.scan_iter(f"{prefix}*"):
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


async def issue(user_id: str, clock: Clock) -> str:
    async with SessionLocal() as s:
        issued = await keys.issue_key(s, user_id, now=clock.now())
        await s.commit()
    return issued.key


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@asynccontextmanager
async def client_for(app: FastAPI, *, clock: Clock, provider: LLMProvider, budget: BudgetSettings | None = None,
                     table: PriceTable | None = None) -> AsyncIterator[tuple[httpx2.AsyncClient, Redis]]:
    """同一プロセスで app を呼ぶクライアント。時計・上流・Redis・モデル（と予算・単価表）を差し替える。"""
    redis = make_redis()
    app.dependency_overrides[get_clock] = lambda: clock
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_model] = lambda: CHAT
    if budget is not None:
        app.dependency_overrides[get_budget_settings] = lambda: budget
    if table is not None:
        app.dependency_overrides[get_price_table] = lambda: table
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
            yield client, redis
    finally:
        app.dependency_overrides.clear()
        await redis.aclose()


@asynccontextmanager
async def mock_provider(*, cache_system: bool = True) -> AsyncIterator[LLMProvider]:
    """接続先を必ず mockllm に向けた Anthropic のプロバイダ（.env で実 API に向けていても課金しない）。"""
    async with open_provider("anthropic", model=CHAT, base_url=BASE.mockllm_url, api_key="mock-key",
                             max_retries=0, timeout=30.0, cache_system=cache_system) as provider:
        yield provider


async def reset_mock() -> None:
    """mockllm の統計とプロンプトキャッシュを消す（前回の実行の「作成済み」が残っていると読み出しになるため）。"""
    async with httpx2.AsyncClient(timeout=5) as c:
        (await c.post(f"{BASE.mockllm_url}/_mock/reset")).raise_for_status()


class CountingProvider:
    """上流を何回呼んだかを数える包み。"""

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
    """relay_chat に渡す要求の代わり（切断されていない）。"""

    async def is_disconnected(self) -> bool:
        return False
