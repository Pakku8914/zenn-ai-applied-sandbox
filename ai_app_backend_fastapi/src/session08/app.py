"""サーバ側でツール呼び出しを回すチャット API（API契約③の tool_call・tool_result を送る）。

起動：APP_MODULE=src.session08.app:app docker compose up -d --wait api

- POST /api/chat/stream … LLM の差分を流しながら、tool_use をサーバで実行して続きを書かせる
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from uuid_utils import uuid7

from kondate.clock import SystemClock
from kondate.settings import get_settings

from .errors import install_error_handling
from .loop import ToolLimits
from .providers import ChatRequest, LLMProvider, open_provider
from .relay import LoopOutcome, relay_tool_loop
from .tools import ToolContext

SYSTEM = "あなたは献立相談AI「こんだてAI」です。レシピの情報は必ずツールで調べ、推測で答えないでください。"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 接続先とキーは ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む。再試行は再試行のセッションで扱う
    async with open_provider("anthropic", model=get_settings().llm_model, timeout=30.0, max_retries=0) as provider:
        app.state.provider = provider
        yield


app = FastAPI(title="こんだてAI（サーバ側のツール呼び出し）", lifespan=lifespan)
app.state.outcomes = deque(maxlen=100)  # 直近のストリームの結末（検証で見る）
app.state.tool_context = ToolContext(clock=SystemClock())
app.state.limits = ToolLimits()
install_error_handling(app)


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


def get_tool_context(request: Request) -> ToolContext:
    return request.app.state.tool_context


def get_limits(request: Request) -> ToolLimits:
    return request.app.state.limits


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/chat/stream", response_class=EventSourceResponse)
async def chat_stream(body: ChatIn, request: Request,
                      provider: Annotated[LLMProvider, Depends(get_provider)],
                      ctx: Annotated[ToolContext, Depends(get_tool_context)],
                      limits: Annotated[ToolLimits, Depends(get_limits)]) -> AsyncIterator[ServerSentEvent]:
    outcome = LoopOutcome(request_id=request.state.request_id, message_id=str(uuid7()))
    chat = ChatRequest(messages=[{"role": "user", "content": body.message}], system=SYSTEM,
                       max_tokens=get_settings().llm_max_tokens)
    events = relay_tool_loop(request, provider, chat, ctx, outcome, limits=limits,
                             on_close=request.app.state.outcomes.append)
    async with aclosing(events):
        async for ev in events:
            yield ev
