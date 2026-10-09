"""リトライ・タイムアウト・フォールバック（上流が不安定でも、重ねすぎず・諦めすぎずに応答する）。

起動：APP_MODULE=src.session11.app:app docker compose up -d --wait api

- POST /api/ask               … primary → light → openai の順に、締め切りの中で再試行して答える。Idempotency-Key に対応
- POST /api/chat/stream       … 最初のイベントまでは同じく再試行・フォールバックし、そのあとは Session 6 と同じ中継
- POST /api/s11/fault/{fault} … /api/ask と同じ処理で、primary の経路にだけ mockllm の障害を付ける（演習用）
フォールバックしたときは、応答ヘッダ x-kondate-fallback と本文の fallback に経路名（light / openai）を入れる。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import replace
from typing import Annotated

import anyio
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from uuid_utils import uuid7

from kondate.cache import make_redis
from kondate.clock import Clock, SystemClock
from kondate.settings import get_settings

from .breaker import BreakerConfig
from .errors import IN_PROGRESS_MESSAGE, ApiError, install_error_handlers
from .fallback import FallbackHeaderMiddleware, ResilientLLM, Route, Served
from .idempotency import KEY_PATTERN, IdempotencyStore, fingerprint
from .providers import ChatRequest, LLMProvider, open_provider
from .relay import StreamOutcome, estimate_input_tokens, relay_chat
from .retry import RetryPolicy

SCOPE = "anonymous"  # この章のアプリは認証を省いている。final では利用者 ID（user.id）を入れる


class ResilienceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESILIENCE_", extra="ignore")

    deadline_seconds: float = 20.0  # 要求1つに許す時間（リトライとフォールバックの合計）
    max_attempts: int = 2  # 経路ごとの試行の回数（最初の1回を含む）
    breaker_failures: int = 5
    breaker_open_seconds: float = 30.0
    openai_fallback: bool = True  # 別の事業者へ送ってよいかは、契約とデータの扱いを確かめてから決める


class OpenAISettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    openai_model: str | None = None


def setup_logging() -> None:
    log = logging.getLogger("kondate.session11")
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)


def build_routes(claude: LLMProvider, oai: LLMProvider, s: ResilienceSettings) -> list[Route]:
    policy = RetryPolicy(max_attempts=s.max_attempts)
    routes = [Route("primary", claude, None, policy),
              Route("light", claude, get_settings().llm_model_light, policy)]
    if s.openai_fallback:
        routes.append(Route("openai", oai, None, policy))
    return routes


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    base, s = get_settings(), ResilienceSettings()
    redis = make_redis()
    try:
        # SDK の自動リトライは 0。再試行は ResilientLLM の1か所だけで行う（二重にしない）
        async with open_provider("anthropic", model=base.llm_model, timeout=30.0, max_retries=0) as claude, \
                open_provider("openai", model=OpenAISettings().openai_model or base.llm_model,
                              timeout=30.0, max_retries=0) as oai:
            app.state.routes, app.state.resilience, app.state.redis = build_routes(claude, oai, s), s, redis
            yield
    finally:
        await redis.aclose()


app = FastAPI(title="こんだてAI（リトライ・タイムアウト・フォールバック）", lifespan=lifespan)
install_error_handlers(app)
app.add_middleware(FallbackHeaderMiddleware)

SYSTEM_CLOCK = SystemClock()


def get_clock() -> Clock:
    return SYSTEM_CLOCK


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


# 演習用の障害注入。クライアントのヘッダは転送せず、決まった3種類だけを primary の経路にだけ付ける
FAULT_HEADERS = {"429": {"x-mock-fault": "429"}, "529": {"x-mock-fault": "529"}, "500": {"x-mock-fault": "500"}}


def with_fault(route: Route, fault: str) -> Route:
    provider = route.provider
    client = getattr(provider, "_client", None)
    headers = FAULT_HEADERS.get(fault)
    if headers is None or client is None or not str(client.base_url).startswith(get_settings().mockllm_url):
        raise ApiError(404, "not_found")  # 本物の API に向いているときは、このエンドポイントは無いものとする
    faulted = type(provider)(client.with_options(default_headers=headers), default_model=provider._model)
    return replace(route, provider=faulted)


def get_llm(request: Request, redis: Annotated[Redis, Depends(get_redis)],
            clock: Annotated[Clock, Depends(get_clock)]) -> ResilientLLM:
    s: ResilienceSettings = request.app.state.resilience
    routes: list[Route] = request.app.state.routes
    fault = request.path_params.get("fault")
    if fault is not None:
        routes = [with_fault(routes[0], fault), *routes[1:]]  # 経路名は primary のまま＝同じブレーカを使う
    breaker = BreakerConfig(failure_threshold=s.breaker_failures, open_seconds=s.breaker_open_seconds)
    return ResilientLLM(routes, redis=redis, clock=clock, deadline_seconds=s.deadline_seconds, breaker=breaker)


def get_store(redis: Annotated[Redis, Depends(get_redis)]) -> IdempotencyStore:
    return IdempotencyStore(redis)


LLMDep = Annotated[ResilientLLM, Depends(get_llm)]
StoreDep = Annotated[IdempotencyStore, Depends(get_store)]


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)


class AskOut(BaseModel):
    text: str
    input_tokens: int
    output_tokens: int
    fallback: str | None  # フォールバックした経路（primary で答えたら null）


def build_chat(body: ChatIn) -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": body.message}],
                       max_tokens=get_settings().llm_max_tokens)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/ask", response_model=AskOut)
async def ask(request: Request, body: ChatIn, llm: LLMDep, store: StoreDep,
              idempotency_key: Annotated[str | None, Header()] = None) -> Response:
    ticket = None
    if idempotency_key is not None:
        if not KEY_PATTERN.match(idempotency_key):
            raise ApiError(422, "invalid_request", "Idempotency-Key の形式が正しくありません")
        fp = fingerprint(request.method, request.url.path, body.model_dump())
        begun = await store.begin(SCOPE, idempotency_key, fp)
        if begun.outcome == "conflict":
            raise ApiError(409, "idempotency_conflict")
        if begun.outcome == "in_progress":
            raise ApiError(409, "idempotency_conflict", IN_PROGRESS_MESSAGE, headers={"retry-after": "1"})
        if begun.outcome == "replay" and begun.saved is not None:
            request.state.fallback = begun.saved.fallback  # 再生でもフォールバックの印は同じにする
            return Response(begun.saved.body, status_code=begun.saved.status, media_type="application/json",
                            headers={"idempotent-replayed": "true"})
        ticket = begun.ticket
    try:
        served = await llm.complete(build_chat(body))
    except BaseException:
        if ticket is not None:  # 失敗は保存しない。記録を消して、同じキーでやり直せるようにする
            with anyio.CancelScope(shield=True):
                await store.abandon(ticket)
        raise
    result = served.value
    content = AskOut(text=result.text, input_tokens=result.usage.input_tokens,
                     output_tokens=result.usage.output_tokens, fallback=served.fallback).model_dump_json()
    if ticket is not None:
        await store.complete(ticket, 200, content, served.fallback)
    request.state.fallback = served.fallback
    return Response(content, media_type="application/json")


# 同じ関数を障害注入つきのパスにも載せる（{fault} は get_llm が request.path_params から読む）
app.post("/api/s11/fault/{fault}", response_model=AskOut)(ask)


async def primed_served(request: Request, body: ChatIn, llm: LLMDep) -> Served:
    """依存関数の中で先読みまでを再試行する。ここで失敗すれば、まだ 200 を返していないので JSON で返せる。"""
    served = await llm.prime(build_chat(body))
    request.state.fallback = served.fallback  # 応答ヘッダは FallbackHeaderMiddleware が付ける
    return served


@app.post("/api/chat/stream", response_class=EventSourceResponse)
async def chat_stream(request: Request,
                      served: Annotated[Served, Depends(primed_served)]) -> AsyncIterator[ServerSentEvent]:
    primed = served.value
    outcome = StreamOutcome(request_id=request.state.request_id, message_id=str(uuid7()),
                            input_estimate=estimate_input_tokens(primed.chat))
    async with aclosing(relay_chat(request, primed, outcome)) as events:  # ここから先は再試行しない
        async for ev in events:
            yield ev
