"""ストリーミングの異常系（API契約③の error イベント・先読み・再送・バッファリング）。

起動：APP_MODULE=src.session06.app:app docker compose up -d --wait api

- POST /api/chat/stream              … 先読みしてから SSE を始める。開始前の失敗は JSON、開始後は error イベント
- POST /api/s06/fault/{fault}        … 同じ処理に mockllm の障害注入を付けたもの（429 / 529 / sse-error / disconnect）
- GET  /api/chat/stream/{message_id} … Last-Event-ID より後ろを Redis から再送する（再送できなければ 204）
- GET  /api/s06/ticks                … バッファリングの再現用（?fix=1 で X-Accel-Buffering: no を付ける）
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from uuid_utils import uuid7

from kondate.cache import make_redis
from kondate.settings import get_settings

from .errors import ApiError, install_error_handlers
from .providers import ChatRequest, LLMProvider, open_provider
from .relay import Primed, StreamOutcome, estimate_input_tokens, prime, relay_chat
from .resume import EventLog, format_entries, load_replay, parse_last_event_id


class StreamSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    openai_model: str | None = None
    anthropic_base_url: str = ""
    openai_base_url: str = ""
    demo_ttft_ms: int = 300  # 上流が mockllm のときだけ付ける遅延（逐次表示を目で見るため）
    demo_tps: int = 40


def demo_headers(s: StreamSettings) -> dict[str, str] | None:
    base = s.anthropic_base_url if s.llm_provider == "anthropic" else s.openai_base_url
    if not base.startswith(get_settings().mockllm_url):
        return None
    return {"x-mock-ttft-ms": str(s.demo_ttft_ms), "x-mock-tps": str(s.demo_tps)}


def setup_logging() -> None:
    log = logging.getLogger("kondate.session06")
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
    redis = make_redis()
    try:
        # 再試行は再試行とフォールバックのセッションで扱うので、SDK の自動再試行は切ったまま
        async with open_provider(s.llm_provider, model=model, timeout=30.0, max_retries=0,
                                 default_headers=demo_headers(s)) as provider:
            app.state.provider, app.state.redis = provider, redis
            yield
    finally:
        await redis.aclose()


app = FastAPI(title="こんだてAI（ストリーミングの異常系）", lifespan=lifespan)
app.state.outcomes = deque(maxlen=100)  # 直近のストリームの結末（検証で見る）
install_error_handlers(app)


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def build_chat(body: ChatIn) -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": body.message}],
                       max_tokens=get_settings().llm_max_tokens)


# 演習用の障害注入。クライアントのヘッダは転送せず、決まった4種類だけを mockllm にだけ付ける
FAULT_HEADERS = {
    "429": {"x-mock-fault": "429"},
    "529": {"x-mock-fault": "529"},
    "sse-error": {"x-mock-fault": "sse-error"},
    "disconnect": {"x-mock-fault": "disconnect"},
}


def with_fault(provider: LLMProvider, fault: str) -> LLMProvider:
    client = getattr(provider, "_client", None)
    headers = FAULT_HEADERS.get(fault)
    if headers is None or client is None or not str(client.base_url).startswith(get_settings().mockllm_url):
        raise ApiError(404, "not_found")  # 本物の API に向いているときは、このエンドポイントは無いものとする
    # with_options は HTTP の接続を共有したまま既定ヘッダだけ足した複製を作る（閉じるのは元のクライアント）
    return type(provider)(client.with_options(default_headers=headers), default_model=provider._model)


async def primed_chat(body: ChatIn, request: Request,
                      provider: Annotated[LLMProvider, Depends(get_provider)]) -> Primed:
    """依存関数の中で先読みする。ここで ProviderError が出れば、例外ハンドラが JSON のエラー本文にする。"""
    fault = request.path_params.get("fault")
    if fault is not None:
        provider = with_fault(provider, fault)
    return await prime(provider, build_chat(body))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/chat/stream", response_class=EventSourceResponse)
async def chat_stream(request: Request, primed: Annotated[Primed, Depends(primed_chat)],
                      redis: Annotated[Redis, Depends(get_redis)]) -> AsyncIterator[ServerSentEvent]:
    # ここに来た時点で、上流は最初のイベントを返している（＝開始前の失敗は起きなかった）
    outcome = StreamOutcome(request_id=request.state.request_id, message_id=str(uuid7()),
                            input_estimate=estimate_input_tokens(primed.chat))
    log = EventLog(redis, outcome.message_id)
    events = relay_chat(request, primed, outcome, on_close=request.app.state.outcomes.append)
    async with aclosing(events):
        async for ev in events:
            yield await log.append(ev)  # id を付け、Redis に書いてから送る


# 同じ関数を障害注入つきのパスにも載せる（{fault} は primed_chat が request.path_params から読む）
app.post("/api/s06/fault/{fault}", response_class=EventSourceResponse)(chat_stream)


@app.get("/api/chat/stream/{message_id}")
async def resume_stream(message_id: UUID, redis: Annotated[Redis, Depends(get_redis)],
                        last_event_id: Annotated[str | None, Header()] = None) -> Response:
    try:
        after = parse_last_event_id(last_event_id)
    except ValueError:
        raise ApiError(422, "invalid_request", "Last-Event-ID の形式が正しくありません") from None
    entries = await load_replay(redis, str(message_id), after)
    if entries is None:
        return Response(status_code=204)  # 再送できるものが無い（知らない ID・期限切れ・途中で終わった）
    # 保存済みの分は一度に返せるので、ふつうの Response で足りる
    return Response(format_entries(entries), media_type="text/event-stream",
                    headers={"cache-control": "no-cache", "x-accel-buffering": "no"})


@app.get("/api/s06/ticks")
async def ticks(fix: bool = False) -> StreamingResponse:
    async def blocks() -> AsyncIterator[str]:
        for n in range(1, 6):
            if n > 1:
                await asyncio.sleep(0.3)
            yield f'id: {n}\nevent: tick\ndata: {{"n": {n}}}\n\n'

    headers = {"cache-control": "no-cache"}
    if fix:
        headers["x-accel-buffering"] = "no"  # nginx に「この応答はためずに流して」と伝える
    return StreamingResponse(blocks(), media_type="text/event-stream", headers=headers)
