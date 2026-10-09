"""Session 15 のテスト対象：小さな献立相談 API。

- POST /api/chat/stream … 先読みしてから SSE（start → delta… → usage → done）。保存してから done を送る
- GET  /api/usage/today … 今日の使用量（Redis の写し）
- GET  /health

テストでは get_provider と get_store を差し替え、httpx2.ASGITransport で同じプロセスから呼ぶ（lifespan は動かさない）。
api コンテナで動かすなら：APP_MODULE=src.session15.app:app docker compose up -d --wait api
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from uuid_utils import uuid7

from kondate.cache import make_redis
from kondate.clock import SystemClock
from kondate.db import SessionLocal, engine
from kondate.settings import get_settings

from .errors import install_error_handlers
from .providers import ChatRequest, LLMProvider, open_provider
from .relay import Primed, StreamOutcome, estimate_input_tokens, prime, relay_chat
from .sse import error_event
from .store import SqlStore, Turn, TurnStore, create_tables

logger = logging.getLogger("kondate.session15.app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await create_tables(engine)
    redis = make_redis()
    try:
        # 接続先は環境変数 ANTHROPIC_BASE_URL（既定は mockllm）。再試行はしない（Session 11 の retry_call で行う）
        async with open_provider("anthropic", model=get_settings().llm_model, timeout=30.0,
                                 max_retries=0) as provider:
            app.state.provider = provider
            app.state.store = SqlStore(SessionLocal, redis, SystemClock())
            yield
    finally:
        await redis.aclose()


app = FastAPI(title="こんだてAI（テスト戦略）", lifespan=lifespan)
install_error_handlers(app)


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


def get_store(request: Request) -> TurnStore:
    return request.app.state.store


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def build_chat(body: ChatIn) -> ChatRequest:
    """上流への要求を作る。録画（record.py）もこの関数を通すので、再生の指紋がアプリと一致する。"""
    return ChatRequest(messages=[{"role": "user", "content": body.message}],
                       max_tokens=get_settings().llm_max_tokens)


async def primed_chat(body: ChatIn, provider: Annotated[LLMProvider, Depends(get_provider)]) -> Primed:
    """依存関数の中で先読みする。ここで ProviderError が出れば、例外ハンドラが JSON のエラー本文にする。"""
    return await prime(provider, build_chat(body))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/chat/stream", response_class=EventSourceResponse)
async def chat_stream(request: Request, primed: Annotated[Primed, Depends(primed_chat)],
                      store: Annotated[TurnStore, Depends(get_store)]) -> AsyncIterator[ServerSentEvent]:
    outcome = StreamOutcome(request_id=request.state.request_id, message_id=str(uuid7()),
                            input_estimate=estimate_input_tokens(primed.chat))
    events = relay_chat(request, primed, outcome)
    async with aclosing(events):
        async for ev in events:
            if ev.event == "done":  # usage を送ったあと・done の前に保存する。保存できなければ done を送らない
                try:
                    await store.save_turn(Turn(
                        message_id=outcome.message_id, request_id=outcome.request_id,
                        prompt=primed.chat.messages[-1]["content"], answer=outcome.text,
                        input_tokens=outcome.usage.input_tokens, output_tokens=outcome.usage.output_tokens))
                except Exception:
                    logger.exception("save_failed request_id=%s", outcome.request_id)
                    yield error_event("internal_error", outcome.request_id)
                    return
            yield ev


@app.get("/api/usage/today")
async def usage_today(store: Annotated[TurnStore, Depends(get_store)]) -> dict:
    return await store.usage_today()
