"""verify.py が使う検証用の小道具（名前が verify で始まらないので単独では実行されない）。

session06/harness.py（serve・wired・clear_keys）、session07/harness.py（dbcheck）、session08/harness.py
（mock_provider・fixture_texts・shape）から必要な分をコピーしたもの。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import uvicorn
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import func, select

from kondate.cache import make_redis
from kondate.clock import FixedClock
from kondate.db import SessionLocal, engine
from kondate.settings import get_settings
from kondate.verifykit import check, sse_events

from . import repo
from .app import get_provider, get_redis, get_tool_context, get_tools
from .models import Message
from .providers import LLMProvider, open_provider
from .resume import PREFIX
from .setup_db import reset_schema
from .tools import TOOLS, Tool, ToolContext

BASE = get_settings()
ROOT = Path(__file__).resolve().parents[2]
PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"

for name in ("kondate.review02",):  # ID やトレースバック入りのログを画面に出さない
    log = logging.getLogger(name)
    log.addHandler(logging.NullHandler())
    log.propagate = False


def fixed_context() -> ToolContext:
    return ToolContext(clock=FixedClock())  # 2026-10-02T18:00+09:00 で止まった時計


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


async def prepare() -> None:
    """スキーマ review02 を作り直し、Redis の review02: で始まるキーだけを消す。"""
    await reset_schema()
    await engine.dispose()
    redis = make_redis()
    try:
        async for key in redis.scan_iter("review02:*"):
            await redis.delete(key)
    finally:
        await redis.aclose()


@asynccontextmanager
async def wired(app: FastAPI, provider: LLMProvider, *, tools: Mapping[str, Tool] | None = None) -> AsyncIterator[Redis]:
    """プロバイダ・Redis・時計・ツールを差し替える。Redis はこの関数を呼んだイベントループの中で作る。"""
    redis = make_redis()
    ctx = fixed_context()
    chosen = tools or TOOLS
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_tool_context] = lambda: ctx
    app.dependency_overrides[get_tools] = lambda: chosen
    try:
        yield redis
    finally:
        app.dependency_overrides.clear()
        await redis.aclose()


@asynccontextmanager
async def asgi_client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    """同じプロセスでアプリを呼ぶ（応答は送り終わってから受け取る。順序と中身の検査に使う）。"""
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
        yield client


def events_of(text: str) -> list[dict]:
    return [e for e in sse_events(text.splitlines()) if e["event"]]  # コメント（: ping）は除く


async def new_conversation(user_id: str = "u001") -> str:
    async with SessionLocal() as s:
        conv = await repo.create_conversation(s, user_id=user_id, title="復習2")
        await s.commit()
        return conv.id


async def count_rows(conversation_id: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(Message)
                              .where(Message.conversation_id == conversation_id))


async def replay_keys() -> int:
    redis = make_redis()
    try:
        return len([k async for k in redis.scan_iter(f"{PREFIX}*")])
    finally:
        await redis.aclose()


def shape(events: list[dict]) -> str:
    """イベント名の列を「start → delta×3 → tool_call」の形に縮める。"""
    runs: list[list] = []
    for ev in events:
        if runs and runs[-1][0] == ev["event"]:
            runs[-1][1] += 1
        else:
            runs.append([ev["event"], 1])
    return " → ".join(k if n == 1 else f"{k}×{n}" for k, n in runs)


def data_of(events: list[dict], name: str) -> list:
    return [e["data"] for e in events if e["event"] == name]


@asynccontextmanager
async def serve(app: FastAPI, port: int) -> AsyncIterator[str]:
    """本物の HTTP サーバ（uvicorn）を同じプロセスで起動する。切断の試験はこちらを使う。"""
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


async def read_until(client: httpx2.AsyncClient, url: str, body: dict, stop_event: str) -> list[dict]:
    """SSE を1ブロックずつ受け取り、stop_event を受け取ったところで接続を閉じる。"""
    got: list[dict] = []
    lines: list[str] = []
    async with client.stream("POST", url, json=body) as r:
        assert r.status_code == 200, r.status_code
        async for line in r.aiter_lines():
            if line != "":
                lines.append(line)
                continue
            got += [e for e in sse_events([*lines, ""]) if e["event"]]
            lines = []
            if got and got[-1]["event"] == stop_event:
                break
    return got


async def wait_until(predicate: Callable[[], bool], timeout: float, what: str) -> None:
    started = time.perf_counter()
    while not predicate():
        if time.perf_counter() - started > timeout:
            raise AssertionError(f"{timeout} 秒待っても {what}")
        await asyncio.sleep(0.05)


@asynccontextmanager
async def mock_provider(name: str = "anthropic") -> AsyncIterator[LLMProvider]:
    """接続先を必ず mockllm に向けたプロバイダ（.env で実 API に向けていても課金しない）。"""
    async with open_provider(name, model=BASE.llm_model,
                             base_url=BASE.mockllm_url if name == "anthropic" else f"{BASE.mockllm_url}/v1",
                             api_key="mock-key", max_retries=0, timeout=30.0) as provider:
        yield provider


def fixture_texts() -> list[str]:
    """mockllm の kondate_tool_search が各ステップで返すテキスト（delta の数の期待値を計算するため）。"""
    data = json.loads((ROOT / "mockllm/fixtures/kondate_tool_search.json").read_text(encoding="utf-8"))
    out = []
    for step in data["steps"]:
        blocks = step.get("content") or [{"type": "text", "text": step.get("text", "")}]
        out.append("".join(b["text"] for b in blocks if b["type"] == "text"))
    return out


async def reset_mock() -> None:
    async with httpx2.AsyncClient(timeout=5) as c:
        (await c.post(f"{BASE.mockllm_url}/_mock/reset")).raise_for_status()
