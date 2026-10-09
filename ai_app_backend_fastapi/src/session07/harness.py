"""verify.py と verify_practice.py が共有する検証用の小道具（名前が verify で始まらないので単独では実行されない）。"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import anthropic
import httpx2
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kondate.db import engine
from kondate.settings import get_settings
from kondate.verifykit import check, eq, sse_events

from . import repo
from .providers import AnthropicProvider
from .tokens import AnthropicTokenCounter

ROOT = Path(__file__).resolve().parents[2]
BASE = get_settings()
INI = "src/session07/alembic.ini"
PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
DAYS = "一二三四五六七八九"

for name in ("kondate.session07", "kondate.session07.errors"):  # ID 入りの警告ログを出さない
    log = logging.getLogger(name)
    log.addHandler(logging.NullHandler())
    log.propagate = False


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


def upgraded(log_text: str) -> list[str]:
    return re.findall(r"Running (?:upgrade|downgrade) \S* ?-> (\S+?),", log_text)


async def reset_schema() -> None:
    """s07 を消して作り直す（他のセッションのスキーマには触れない）。"""
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS s07 CASCADE"))


async def scalar(sql: str) -> object:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql))).scalar()


def day_turn(i: int) -> tuple[str, str]:
    d = DAYS[i]
    return f"{d}日目の夕飯の献立を考えてください。", f"{d}日目は鶏むね肉とキャベツの塩炒めにしましょう。"


def seed_messages(turns: int) -> list[dict]:
    """1往復 48 トークン（user 21・assistant 27）の履歴を turns 往復と、最後に PROMPT（30）を並べる。"""
    out: list[dict] = []
    for i in range(turns):
        u, a = day_turn(i % len(DAYS))
        out += [{"role": "user", "content": [{"type": "text", "text": u}]},
                {"role": "assistant", "content": [{"type": "text", "text": a}]}]
    return [*out, {"role": "user", "content": [{"type": "text", "text": PROMPT}]}]


async def seed_turns(session: AsyncSession, conversation_id: str, turns: int) -> None:
    for i in range(turns):
        u, a = day_turn(i)
        await repo.append_turn(session, conversation_id, user_content=u,
                               assistant_content=[{"type": "text", "text": a}])


@asynccontextmanager
async def mock_llm(fault: str | None = None) -> AsyncIterator[tuple[AnthropicProvider, AnthropicTokenCounter]]:
    """接続先とキーを明示的に mockllm に向けたプロバイダとカウンタ（.env で実 API に向けていても課金しない）。"""
    client = anthropic.AsyncAnthropic(base_url=BASE.mockllm_url, api_key="mock-key", max_retries=0, timeout=10.0,
                                      default_headers={"x-mock-fault": fault} if fault else None)
    try:
        yield (AnthropicProvider(client, default_model=BASE.llm_model),
               AnthropicTokenCounter(client, model=BASE.llm_model))
    finally:
        await client.close()


async def reset_mock() -> None:
    async with httpx2.AsyncClient(timeout=5) as c:
        (await c.post(f"{BASE.mockllm_url}/_mock/reset")).raise_for_status()


async def mock_stats() -> dict:
    async with httpx2.AsyncClient(timeout=5) as c:
        return (await c.get(f"{BASE.mockllm_url}/_mock/stats")).json()


@asynccontextmanager
async def client_for(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    # 想定外の例外も 500 の本文として受け取る（既定ではテスト側へ例外が飛んでくる）
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
        yield client


async def post_sse(client: httpx2.AsyncClient, url: str, body: dict) -> tuple[int, list[dict]]:
    r = await client.post(url, json=body)
    if r.status_code != 200:
        return r.status_code, [r.json()]
    return 200, [ev for ev in sse_events(r.text.splitlines()) if ev["event"]]  # コメント（: ping）は除く


def shape(events: list[dict]) -> str:
    """イベント名の列を「start → delta×32 → usage → done」の形に縮める。"""
    runs: list[list] = []
    for ev in events:
        if runs and runs[-1][0] == ev["event"]:
            runs[-1][1] += 1
        else:
            runs.append([ev["event"], 1])
    return " → ".join(k if n == 1 else f"{k}×{n}" for k, n in runs)
