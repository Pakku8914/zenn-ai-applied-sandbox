"""SSE ストリーミング（API契約③）。

起動：APP_MODULE=src.session05.app:app docker compose up -d --wait api

- GET  /api/s05/wire     … 手書きの SSE（行形式の見本）
- GET  /api/s05/escape   … fastapi.sse の data= と raw_data= の違い
- POST /api/chat/stream  … LLM の差分を start → delta… → usage → done で中継する
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from uuid_utils import uuid7

from kondate.settings import get_settings

from .errors import install_error_handling
from .providers import ChatRequest, LLMProvider, open_provider
from .relay import StreamOutcome, relay_chat
from .sse import sse_event


class StreamSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    openai_model: str | None = None
    anthropic_base_url: str = ""
    openai_base_url: str = ""
    # 上流が mockllm のときだけ付ける遅延（逐次表示を目で見るため）。本物の API には送らない
    demo_ttft_ms: int = 300
    demo_tps: int = 40


def demo_headers(s: StreamSettings) -> dict[str, str] | None:
    base = s.anthropic_base_url if s.llm_provider == "anthropic" else s.openai_base_url
    if not base.startswith(get_settings().mockllm_url):
        return None
    return {"x-mock-ttft-ms": str(s.demo_ttft_ms), "x-mock-tps": str(s.demo_tps)}


def setup_logging() -> None:
    """出力先を1つだけ付ける（構造化ログはセッション14で扱う）。"""
    log = logging.getLogger("kondate.session05")
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    s = StreamSettings()
    model = (s.openai_model if s.llm_provider == "openai" else None) or get_settings().llm_model
    # 再試行は再試行とフォールバックのセッションで扱うので、ここでは SDK の自動再試行を切る
    async with open_provider(s.llm_provider, model=model, timeout=30.0, max_retries=0,
                             default_headers=demo_headers(s)) as provider:
        app.state.provider = provider
        yield


app = FastAPI(title="こんだてAI（SSE ストリーミング）", lifespan=lifespan)
app.state.outcomes = deque(maxlen=100)  # 直近のストリームの結末（検証で見る）
install_error_handling(app)


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# 手書きの SSE。1つの要素が1つのブロック（空行で終わる）
WIRE_BLOCKS = [
    ": こんだてAI の SSE の見本です。コロンで始まる行はコメントです\n\n",
    "retry: 3000\n\n",
    'id: 1\nevent: start\ndata: {"message_id": "demo"}\n\n',
    'id: 2\nevent: delta\ndata: {"text": "鶏むね肉と"}\n\n',
    'id: 3\nevent: delta\ndata: {"text": "キャベツの塩炒め"}\n\n',
    "event: note\ndata: 1行目\ndata: 2行目\n\n",
    'id: 4\nevent: done\ndata: {"stop_reason": "end_turn"}\n\n',
]


@app.get("/api/s05/wire")
async def wire() -> StreamingResponse:
    async def blocks() -> AsyncIterator[str]:
        for block in WIRE_BLOCKS:
            yield block
            await asyncio.sleep(0.2)  # 1ブロックずつ届く様子を見るための間

    return StreamingResponse(blocks(), media_type="text/event-stream", headers={"cache-control": "no-cache"})


@app.get("/api/s05/escape", response_class=EventSourceResponse)
async def escape() -> AsyncIterator[ServerSentEvent]:
    yield ServerSentEvent(event="delta", data={"text": "鶏むね肉"})  # 日本語が \uXXXX になる
    yield sse_event("delta", {"text": "鶏むね肉"})  # raw_data：自分で直列化した文字列をそのまま送る


@app.post("/api/chat/stream", response_class=EventSourceResponse)
async def chat_stream(body: ChatIn, request: Request,
                      provider: Annotated[LLMProvider, Depends(get_provider)]) -> AsyncIterator[ServerSentEvent]:
    # ここに届いた時点で本文の検証は済んでいる。形式の誤りは 422 の JSON で返り、ストリームは始まらない
    outcome = StreamOutcome(request_id=request.state.request_id, message_id=str(uuid7()))
    chat = ChatRequest(messages=[{"role": "user", "content": body.message}],
                       max_tokens=get_settings().llm_max_tokens)
    events = relay_chat(request, provider, chat, outcome, on_close=request.app.state.outcomes.append)
    async with aclosing(events):  # このジェネレータが閉じられたら、中継のジェネレータも確実に閉じる
        async for ev in events:
            yield ev
