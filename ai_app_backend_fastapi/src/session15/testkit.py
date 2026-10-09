"""テストの小道具（tests/・practice/・verify・record が共有する）。

- read_sse()：SSE を1行ずつ読み、空行ごとにイベントへまとめる。ASGITransport でも本物のサーバでも同じ書き方で読める
- wired() / chat_once()：依存性（プロバイダ・保存先）を差し替えて、アプリを同じプロセスから1回呼ぶ
- mock_provider() / chat_via_mock()：mockllm に向けた本物の SDK（障害注入ヘッダ付き）。.env の向き先に関係なく mockllm に向く
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field

import anthropic
import httpx2
from fastapi import FastAPI

from kondate.settings import get_settings
from kondate.verifykit import sse_events

from .app import app as default_app
from .app import get_provider, get_store
from .providers import AnthropicProvider, ChatRequest, LLMProvider
from .store import TurnStore

PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
FAKE_ANSWER = "鶏むね肉とキャベツの塩炒めがおすすめです。"  # 21文字 → 6文字ずつで delta×4
TEXT_REQ = ChatRequest(messages=[{"role": "user", "content": PROMPT}])
TERMINAL = frozenset({"done", "error"})


# ---------------------------------------------------------------- SSE を読む


@dataclass
class SseRun:
    status: int
    headers: httpx2.Headers
    events: list[dict] = field(default_factory=list)  # {"event", "data", "id", "comments"}（コメントだけの塊は除く）
    data_lines: list[str] = field(default_factory=list)  # data: 行の値（1行の JSON か・日本語のままかを見る）
    body: dict | None = None  # 200 の SSE でなかったとき、JSON のエラー本文

    def names(self) -> list[str]:
        return [e["event"] for e in self.events]

    def shape(self) -> str:
        """イベント名の列を「start → delta×3 → usage → done」の形に縮める。"""
        runs: list[list] = []
        for name in self.names():
            if runs and runs[-1][0] == name:
                runs[-1][1] += 1
            else:
                runs.append([name, 1])
        return " → ".join(k if n == 1 else f"{k}×{n}" for k, n in runs)

    def data_of(self, name: str) -> list:
        return [e["data"] for e in self.events if e["event"] == name]


async def read_sse(client: httpx2.AsyncClient, url: str, payload: dict, *, stop_at_terminal: bool = True,
                   timeout: float = 10.0) -> SseRun:
    """POST して SSE をストリームとして読む。done か error を受け取ったら読むのをやめる（stop_at_terminal）。"""
    async with asyncio.timeout(timeout):  # 終わらないストリームでテストが固まらないように
        async with client.stream("POST", url, json=payload) as r:
            if r.status_code != 200 or not r.headers.get("content-type", "").startswith("text/event-stream"):
                await r.aread()
                is_json = r.headers.get("content-type", "").startswith("application/json")
                return SseRun(r.status_code, r.headers, body=r.json() if is_json else None)
            run = SseRun(r.status_code, r.headers)
            block: list[str] = []
            async for line in r.aiter_lines():
                if line != "":
                    block.append(line)
                    if line.startswith("data:"):
                        run.data_lines.append(line.removeprefix("data:").removeprefix(" "))
                    continue
                run.events += [e for e in sse_events([*block, ""]) if e["event"]]  # : ping などは除く
                block = []
                if stop_at_terminal and run.events and run.events[-1]["event"] in TERMINAL:
                    break
            return run


async def post_chat(client: httpx2.AsyncClient, message: str = PROMPT, **options) -> SseRun:
    return await read_sse(client, "/api/chat/stream", {"message": message}, **options)


# ---------------------------------------------------------------- 依存性の差し替えと呼び出し


def _const(value):
    # lambda v=value: v と書くと、FastAPI が v をクエリパラメータと見なして既定値を deepcopy し、落ちる
    return lambda: value


@contextmanager
def wired(app: FastAPI, *, provider: LLMProvider, store: TurnStore) -> Iterator[None]:
    app.dependency_overrides[get_provider] = _const(provider)
    app.dependency_overrides[get_store] = _const(store)
    try:
        yield
    finally:
        app.dependency_overrides.clear()


@asynccontextmanager
async def asgi_client(app: FastAPI = default_app) -> AsyncIterator[httpx2.AsyncClient]:
    # 想定外の例外も 500 の本文として受け取る（既定ではテスト側へ例外が飛んでくる）
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
        yield client


async def chat_once(provider: LLMProvider, store: TurnStore, message: str = PROMPT, **options) -> SseRun:
    """プロバイダと保存先を差し替えて、POST /api/chat/stream を1回呼ぶ。"""
    with wired(default_app, provider=provider, store=store):
        async with asgi_client() as c:
            return await post_chat(c, message, **options)


# ---------------------------------------------------------------- mockllm


@asynccontextmanager
async def mock_provider(headers: dict[str, str] | None = None) -> AsyncIterator[AnthropicProvider]:
    """mockllm に向けた本物の SDK。障害注入のヘッダはこのクライアントにだけ付く。"""
    s = get_settings()
    client = anthropic.AsyncAnthropic(base_url=s.mockllm_url, api_key="mock-key", max_retries=0,
                                      timeout=10.0, default_headers=headers)
    try:
        yield AnthropicProvider(client, default_model=s.llm_model)
    finally:
        await client.close()


async def chat_via_mock(headers: dict[str, str] | None, store: TurnStore, message: str = PROMPT) -> SseRun:
    async with mock_provider(headers) as provider:
        return await chat_once(provider, store, message)


async def reset_mock() -> None:
    async with httpx2.AsyncClient(timeout=5) as c:
        (await c.post(f"{get_settings().mockllm_url}/_mock/reset")).raise_for_status()


async def mock_stats() -> dict:
    async with httpx2.AsyncClient(timeout=5) as c:
        r = await c.get(f"{get_settings().mockllm_url}/_mock/stats")
        r.raise_for_status()
        return r.json()
