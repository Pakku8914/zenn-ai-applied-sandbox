"""verify.py と verify_practice.py が共有する検証用の小道具（名前が verify で始まらないので単独では実行されない）。"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from fastapi import FastAPI
from redis.asyncio import Redis

from kondate.cache import make_redis
from kondate.clock import FixedClock
from kondate.settings import get_settings
from kondate.verifykit import eq

from .app import get_llm, get_redis
from .breaker import BreakerConfig
from .fallback import ResilientLLM, Route
from .providers import ChatRequest, LLMProvider, open_provider
from .retry import FakeSleep

PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
FAKE_TEXT = "鶏むね肉とキャベツの塩炒めがおすすめです。"  # 21文字 → 6文字ずつ4つの差分
ASK = {"message": PROMPT}
LIGHT = get_settings().llm_model_light  # 本文には書かない（モデル ID は設定にだけ置く）
REQ_ID = re.compile(r"^req_[0-9A-HJKMNP-TV-Z]{26}$")

# ログは画面に出さない（期待される出力に request_id などを混ぜないため）
_root = logging.getLogger("kondate.session11")
_root.propagate = False
_root.setLevel(logging.INFO)
_root.addHandler(logging.NullHandler())


def chat() -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": PROMPT}], max_tokens=1024)


async def clear_redis(prefix: str = "s11:") -> None:
    """Redis の s11: で始まるキーだけを消す。"""
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


async def reset_mock() -> None:
    async with httpx2.AsyncClient(timeout=5) as c:
        (await c.post(f"{get_settings().mockllm_url}/_mock/reset")).raise_for_status()


async def mock_stats() -> dict:
    async with httpx2.AsyncClient(timeout=5) as c:
        r = await c.get(f"{get_settings().mockllm_url}/_mock/stats")
        r.raise_for_status()
        return r.json()


async def fault_stats(key: str) -> dict:
    """x-mock-fault-key で名前を付けた障害の数え（calls・injected・retry_counts）。"""
    return (await mock_stats())["faults"][key]


@asynccontextmanager
async def mock_provider(name: str = "anthropic", headers: dict[str, str] | None = None,
                        **options: Any) -> AsyncIterator[LLMProvider]:
    """接続先を必ず mockllm に向けたプロバイダ。max_retries を渡さなければ SDK の既定（2）になる。"""
    s = get_settings()
    base = s.mockllm_url if name == "anthropic" else f"{s.mockllm_url}/v1"
    async with open_provider(name, model=s.llm_model, base_url=base, api_key="mock-key", timeout=30.0,
                             default_headers=headers, **options) as provider:
        yield provider


def resilient(routes: Sequence[Route], redis: Redis, clock: FixedClock, *, breaker: BreakerConfig = BreakerConfig(),
              deadline: float = 20.0) -> tuple[ResilientLLM, FakeSleep]:
    """FakeSleep（実際には待たない）とジッタ 1.0（上限ちょうど）で組んだ ResilientLLM。"""
    sleep = FakeSleep(clock)
    llm = ResilientLLM(routes, redis=redis, clock=clock, deadline_seconds=deadline, breaker=breaker,
                       sleep=sleep, rand=lambda: 1.0)
    return llm, sleep


@asynccontextmanager
async def client_for(app: FastAPI, llm: ResilientLLM, redis: Redis) -> AsyncIterator[httpx2.AsyncClient]:
    """同一プロセスで app を呼ぶクライアント。上流（ResilientLLM）と Redis を差し替える（lifespan は動かない）。"""
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_redis] = lambda: redis
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


class Connected:
    """relay_chat に渡す要求の代わり（切断されていない）。"""

    async def is_disconnected(self) -> bool:
        return False


def assert_error(r: httpx2.Response, status: int, type_: str) -> None:
    """共通エラー本文の形・request_id・上流の文が漏れていないことをまとめて確かめる。"""
    eq(r.status_code, status, f"status（本文 {r.text}）")
    err = r.json()["error"]
    eq(sorted(err), ["message", "request_id", "type"], "error のキー")
    eq(err["type"], type_, "error.type")
    assert REQ_ID.match(err["request_id"]), err["request_id"]
    eq(r.headers["x-request-id"], err["request_id"], "x-request-id ヘッダと本文の request_id")
    assert "mockllm" not in r.text and "req_mock_" not in r.text, f"上流の文が漏れている: {r.text}"
