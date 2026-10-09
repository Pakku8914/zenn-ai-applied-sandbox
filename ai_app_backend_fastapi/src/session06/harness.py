"""verify.py・verify_practice.py・proxy_check.py が共有する検証用の小道具（session05/harness.py のコピーに Redis を足したもの）。

名前が verify で始まらないので verify-all.sh には拾われない。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass, field

import httpx2
import uvicorn
from fastapi import FastAPI
from redis.asyncio import Redis

from kondate.cache import make_redis
from kondate.settings import get_settings
from kondate.verifykit import sse_events

from .app import get_provider, get_redis
from .providers import ChatRequest, ChatResult, Done, LLMProvider, StreamEvent, TextDelta, open_provider

BASE = get_settings()
PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"


def quiet_logs() -> list[str]:
    """kondate.session06 のログを画面に出さずに集める（期待される出力に ID を混ぜないため）。"""
    lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(record.getMessage())

    log = logging.getLogger("kondate.session06")
    for handler in list(log.handlers):
        log.removeHandler(handler)
    log.addHandler(Capture())
    log.setLevel(logging.INFO)
    log.propagate = False
    return lines


@asynccontextmanager
async def mock_provider(name: str = "anthropic", headers: dict[str, str] | None = None) -> AsyncIterator[LLMProvider]:
    """接続先を必ず mockllm に向けたプロバイダ。headers は x-mock-* の遅延・障害注入ヘッダ。"""
    async with open_provider(
        name, model=BASE.llm_model,
        base_url=BASE.mockllm_url if name == "anthropic" else f"{BASE.mockllm_url}/v1",
        api_key="mock-key", max_retries=0, timeout=60.0, default_headers=headers,
    ) as provider:
        yield provider


@asynccontextmanager
async def wired(app: FastAPI, provider: LLMProvider) -> AsyncIterator[Redis]:
    """get_provider と get_redis を差し替える。Redis はこの関数を呼んだイベントループの中で作る。"""
    redis = make_redis()
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_redis] = lambda: redis
    try:
        yield redis
    finally:
        app.dependency_overrides.clear()
        await redis.aclose()


async def clear_keys() -> None:
    """Redis の s06: で始まるキーだけを消す（他のセッションのキーには触れない）。"""
    redis = make_redis()
    try:
        async for key in redis.scan_iter("s06:*"):
            await redis.delete(key)
    finally:
        await redis.aclose()


@asynccontextmanager
async def asgi_client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    """同じプロセスでアプリを呼ぶ（応答は送り終わってから受け取る。順序と中身の検査に使う）。"""
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
        yield client


@asynccontextmanager
async def serve(app: FastAPI, port: int) -> AsyncIterator[str]:
    """本物の HTTP サーバ（uvicorn）を同じプロセスで起動する。時間の計測と切断の試験はこちらを使う。"""
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


@dataclass
class Received:
    events: list[dict] = field(default_factory=list)
    at: list[float] = field(default_factory=list)  # 各ブロックを受け取った時刻（送信からの秒）

    def names(self) -> list[str | None]:
        return [e["event"] for e in self.events]


async def read_stream(client: httpx2.AsyncClient, method: str, url: str, body: dict | None = None, *,
                      stop_after_deltas: int | None = None) -> Received:
    """SSE を1ブロックずつ受け取り、時刻を記録する。stop_after_deltas 個の delta で接続を閉じる。"""
    got = Received()
    started = time.perf_counter()
    lines: list[str] = []
    async with client.stream(method, url, json=body) as r:
        assert r.status_code == 200, r.status_code
        async for line in r.aiter_lines():
            if line != "":
                lines.append(line)
                continue
            got.events += sse_events([*lines, ""])
            got.at.append(time.perf_counter() - started)
            lines = []
            if stop_after_deltas is not None and got.names().count("delta") >= stop_after_deltas:
                break
    return got


def shape(names: list[str | None]) -> str:
    """["start", "delta", "delta", "error"] を「start → delta×2 → error」に縮める。"""
    runs: list[list] = []
    for n in names:
        label = n or ": ping"
        if runs and runs[-1][0] == label:
            runs[-1][1] += 1
        else:
            runs.append([label, 1])
    return " → ".join(k if c == 1 else f"{k}×{c}" for k, c in runs)


async def wait_until(predicate, timeout: float, what: str) -> float:
    started = time.perf_counter()
    while not predicate():
        if time.perf_counter() - started > timeout:
            raise AssertionError(f"{timeout} 秒待っても {what}")
        await asyncio.sleep(0.05)
    return time.perf_counter() - started


class CountingProvider:
    """上流から差分をいくつ読んだか・最後まで読んだか・閉じたかを数える包み（検証用）。"""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner, self.name = inner, inner.name
        self.pulled = 0
        self.finished = False
        self.closed = False

    async def complete(self, req: ChatRequest) -> ChatResult:
        return await self.inner.complete(req)

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        try:
            async with aclosing(self.inner.stream(req)) as upstream:
                async for ev in upstream:
                    if isinstance(ev, TextDelta):
                        self.pulled += 1
                    elif isinstance(ev, Done):
                        self.finished = True
                    yield ev
        finally:
            self.closed = True
