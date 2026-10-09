"""verify.py と test_mid01.py が共有する検証用の小道具（名前が verify で始まらないので単独では実行されない）。

session07 の harness（Alembic・スキーマの初期化）と session08 の harness（mockllm・イベント列の要約）、
session06 の harness（uvicorn を同じプロセスで起動して切断を試す）を合わせたもの。
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import subprocess
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import anthropic
import httpx2
import uvicorn
from fastapi import FastAPI
from sqlalchemy import text

from kondate.clock import FixedClock
from kondate.db import engine
from kondate.settings import get_settings
from kondate.verifykit import check, eq, sse_events

from .app import HistorySettings, get_counter, get_history_settings, get_limits, get_provider, get_tool_context
from .loop import ToolLimits
from .providers import (AnthropicProvider, ChatRequest, ChatResult, Done, FakeProvider, LLMProvider, StreamEvent,
                        ToolCall, fake_script)
from .tokens import AnthropicTokenCounter, ApproxTokenCounter, TokenCounter
from .tools import ToolContext

BASE = get_settings()
ROOT = Path(__file__).resolve().parents[2]
INI = "src/mid01/alembic.ini"
PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
PORT = 18790
FIXTURE_CALLS = [("search_recipes", {"ingredients": ["鶏むね肉", "キャベツ"], "max_minutes": 20}),
                 ("get_recipe", {"recipe_id": "R001"})]

for _name in ("kondate.mid01",):  # ID やトレースバック入りのログを画面に出さない
    _log = logging.getLogger(_name)
    _log.addHandler(logging.NullHandler())
    _log.propagate = False


# ---------------------------------------------------------------- DB と Alembic


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
    """mid01 を消して作り直す（他のセッションのスキーマには触れない）。"""
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS mid01 CASCADE"))


async def fetch(sql: str) -> list:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql))).scalars())


# ---------------------------------------------------------------- 依存性の差し替え


def _const(value):
    # lambda v=value: v と書くと、FastAPI が v をクエリパラメータと見なして既定値を deepcopy し、落ちる
    return lambda: value


@contextmanager
def wired(app: FastAPI, provider: LLMProvider, *, counter: TokenCounter | None = None,
          limits: ToolLimits | None = None, budget: int | None = None) -> Iterator[None]:
    """プロバイダ・カウンタ・時計・上限を差し替える。カウンタを省くと手元の近似（mockllm と同じ式）にする。"""
    app.dependency_overrides.clear()
    app.dependency_overrides[get_provider] = _const(provider)
    app.dependency_overrides[get_counter] = _const(counter or ApproxTokenCounter())
    app.dependency_overrides[get_tool_context] = _const(ToolContext(clock=FixedClock()))
    app.dependency_overrides[get_limits] = _const(limits or ToolLimits())
    if budget is not None:
        app.dependency_overrides[get_history_settings] = _const(HistorySettings(history_max_input_tokens=budget))
    try:
        yield
    finally:
        app.dependency_overrides.clear()


@asynccontextmanager
async def mock_llm(headers: dict[str, str] | None = None) -> AsyncIterator[tuple[LLMProvider, TokenCounter]]:
    """mockllm に向けたプロバイダとカウンタ（.env で実 API に向けていても課金しない）。

    障害注入のヘッダはプロバイダのクライアントにだけ付ける（count_tokens は正常に答えさせる）。
    """
    def client(h: dict[str, str] | None) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(base_url=BASE.mockllm_url, api_key="mock-key", max_retries=0,
                                        timeout=30.0, default_headers=h)

    chat, count = client(headers), client(None)
    try:
        yield (AnthropicProvider(chat, default_model=BASE.llm_model),
               AnthropicTokenCounter(count, model=BASE.llm_model))
    finally:
        await chat.close()
        await count.close()


async def reset_mock() -> None:
    async with httpx2.AsyncClient(timeout=5) as c:
        (await c.post(f"{BASE.mockllm_url}/_mock/reset")).raise_for_status()


async def mock_stats() -> dict:
    async with httpx2.AsyncClient(timeout=5) as c:
        r = await c.get(f"{BASE.mockllm_url}/_mock/stats")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------- HTTP の呼び出しと結果の要約


@asynccontextmanager
async def asgi_client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    # 想定外の例外も 500 の本文として受け取る（既定ではテスト側へ例外が飛んでくる）
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
        yield client


async def new_conversation(c: httpx2.AsyncClient) -> str:
    r = await c.post("/api/conversations", json={})
    eq(r.status_code, 201, "会話の作成")
    return r.json()["id"]


async def post_message(c: httpx2.AsyncClient, cid: str, content: str) -> tuple[httpx2.Response, list[dict]]:
    r = await c.post(f"/api/conversations/{cid}/messages", json={"content": content})
    events = [e for e in sse_events(r.text.splitlines()) if e["event"]] if r.status_code == 200 else []
    return r, events  # コメント（: ping）は除く


async def stored(c: httpx2.AsyncClient, cid: str) -> list[dict]:
    r = await c.get(f"/api/conversations/{cid}")
    eq(r.status_code, 200, "会話の取得")
    return r.json()["messages"]


def rows_of(messages: list[dict]) -> list[tuple]:
    return [(m["role"], m["status"], m["stop_reason"]) for m in messages]


def as_messages(messages: list[dict]) -> list[dict]:
    return [{"role": m["role"], "content": m["content"]} for m in messages]


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


def pairs_ok(messages: list[dict]) -> bool:
    """tool_use を含む assistant の直後に、同じ id の tool_result だけを持つ user があるか（session08 から）。"""
    for i, m in enumerate(messages):
        uses = [b["id"] for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"] \
            if m["role"] == "assistant" and isinstance(m["content"], list) else []
        if not uses:
            continue
        nxt = messages[i + 1] if i + 1 < len(messages) else None
        if nxt is None or nxt["role"] != "user":
            return False
        if [b.get("tool_use_id") for b in nxt["content"]] != uses:
            return False
    return True


def alternates(messages: list[dict]) -> bool:
    """user と assistant が交互に並んでいるか（同じ role が2つ続かないか）。"""
    return all(a["role"] != b["role"] for a, b in zip(messages, messages[1:]))


# ---------------------------------------------------------------- 台本


def fixture_texts() -> list[str]:
    """mockllm の kondate_tool_search が各ステップで返すテキスト。"""
    data = json.loads((ROOT / "mockllm/fixtures/kondate_tool_search.json").read_text(encoding="utf-8"))
    out = []
    for step in data["steps"]:
        blocks = step.get("content") or [{"type": "text", "text": step.get("text", "")}]
        out.append("".join(b["text"] for b in blocks if b["type"] == "text"))
    return out


def expected_shape() -> str:
    n = [math.ceil(len(t) / 6) for t in fixture_texts()]  # mockllm も fake_script も text_delta を6文字ずつ送る
    return (f"start → delta×{n[0]} → tool_call → tool_result → delta×{n[1]} → tool_call → tool_result → "
            f"delta×{n[2]} → usage → done")


def fake_tool_search() -> FakeProvider:
    """mockllm の kondate_tool_search と同じ3ステップを返す Fake（同じテストを両方に流すため）。"""
    t = fixture_texts()
    return FakeProvider(fake_script(t[0], tool_calls=[ToolCall("toolu_f1", *FIXTURE_CALLS[0])]),
                        fake_script(t[1], tool_calls=[ToolCall("toolu_f2", *FIXTURE_CALLS[1])]),
                        fake_script(t[2]))


def tool_turn(tool_id: str) -> list[list]:
    """get_recipe(R001) を1回呼んでから答える、1往復ぶんの台本（2ステップ）。"""
    return [fake_script("確認しますね。", tool_calls=[ToolCall(tool_id, "get_recipe", {"recipe_id": "R001"})]),
            fake_script("R001 は15分で作れます。")]


# ---------------------------------------------------------------- 本物の HTTP サーバでの切断（session06 から）


@asynccontextmanager
async def serve(app: FastAPI, port: int) -> AsyncIterator[str]:
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


async def read_until(url: str, body: dict, stop: str) -> list[dict]:
    """SSE を1イベントずつ読み、stop のイベントを受け取ったところで接続を閉じる。"""
    got: list[dict] = []
    lines: list[str] = []
    async with httpx2.AsyncClient(timeout=30) as c:
        async with c.stream("POST", url, json=body) as r:
            eq(r.status_code, 200, "status")
            async for line in r.aiter_lines():
                if line != "":
                    lines.append(line)
                    continue
                got += [e for e in sse_events([*lines, ""]) if e["event"]]
                lines = []
                if got and got[-1]["event"] == stop:
                    break
    return got


async def wait_until(predicate: Callable[[], bool], timeout: float, what: str) -> None:
    started = time.perf_counter()
    while not predicate():
        if time.perf_counter() - started > timeout:
            raise AssertionError(f"{timeout} 秒待っても {what}")
        await asyncio.sleep(0.05)


class PausingProvider:
    """pause_on 回目の呼び出しだけ、最初のイベントの前に seconds 秒待つ包み（切断の試験用）。"""

    def __init__(self, inner: LLMProvider, *, pause_on: int, seconds: float) -> None:
        self.inner, self.name = inner, inner.name
        self.pause_on, self.seconds = pause_on, seconds
        self.calls = 0  # stream() が呼ばれた回数
        self.finished = 0  # Done まで読まれた回数

    async def complete(self, req: ChatRequest) -> ChatResult:
        return await self.inner.complete(req)

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        if self.calls == self.pause_on:
            await asyncio.sleep(self.seconds)
        async for ev in self.inner.stream(req):
            if isinstance(ev, Done):
                self.finished += 1
            yield ev
