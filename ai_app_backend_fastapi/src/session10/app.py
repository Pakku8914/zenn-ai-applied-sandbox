"""レート制限とクォータ（プランごとの回数とトークン量を Redis で数え、上流の 429 と矛盾させない）。

事前に（api コンテナの /app で）：
  docker compose exec api python -m src.session10.cli setup
  docker compose exec api python -m src.session10.cli issue u001
起動：APP_MODULE=src.session10.app:app docker compose up -d --wait api

- GET  /api/usage        … 今日の使用量とプランの上限（レート制限の回数は減らさない）
- POST /api/ask          … 1回で答えを返す。レート制限 → 上流の待ち時間 → 予約 → 上流 → 精算
- POST /api/chat/stream  … SSE で返す。精算はストリームの終わり（完了・失敗・切断のどれでも）
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from uuid_utils import uuid7

from kondate.cache import make_redis
from kondate.db import engine
from kondate.settings import get_settings

from .auth import ClockDep, CurrentUserDep
from .errors import install_error_handlers
from .limiter import Reservation
from .providers import ChatRequest, LLMProvider, open_provider
from .ratelimit import (Admission, LimiterDep, LimitSettingsDep, RateLimitDep, check_upstream_cooldown,
                        release_after_failure, reservation_amount, reserve_tokens, settle, token_headers,
                        usage_today, usage_tokens)
from .relay import Primed, StreamOutcome, estimate_input_tokens, prime
from .stream import settled_events


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    openai_model: str | None = None


def setup_logging() -> None:
    log = logging.getLogger("kondate.session10")
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    s = LLMSettings()
    model = (s.openai_model if s.llm_provider == "openai" else None) or get_settings().llm_model
    redis = make_redis()
    try:
        # 上流へのリトライはリトライのセッションで扱う。ここでは SDK の自動リトライを切って、429 をそのまま見る
        async with open_provider(s.llm_provider, model=model, timeout=30.0, max_retries=0) as provider:
            app.state.provider, app.state.redis = provider, redis
            yield
    finally:
        await redis.aclose()
        await engine.dispose()


app = FastAPI(title="こんだてAI（レート制限とクォータ）", lifespan=lifespan)
install_error_handlers(app)


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


ProviderDep = Annotated[LLMProvider, Depends(get_provider)]


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)


def build_chat(body: ChatIn) -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": body.message}],
                       max_tokens=get_settings().llm_max_tokens)


class UsageOut(BaseModel):
    plan: str
    used_today: int
    limit_today: int
    requests_per_minute: int


class AskOut(BaseModel):
    text: str
    input_tokens: int
    output_tokens: int
    used_today: int


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/usage")
async def get_usage(user: CurrentUserDep, limiter: LimiterDep, settings: LimitSettingsDep,
                    clock: ClockDep) -> UsageOut:
    data = await usage_today(limiter, user, settings, clock.now())
    return UsageOut(**data)


@app.post("/api/ask")
async def ask(body: ChatIn, response: Response, admission: RateLimitDep, limiter: LimiterDep,
              settings: LimitSettingsDep, clock: ClockDep, provider: ProviderDep) -> AskOut:
    chat = build_chat(body)
    now = clock.now()
    await check_upstream_cooldown(limiter, now)
    reservation = await reserve_tokens(limiter, admission, reservation_amount(chat), now, settings)
    try:
        result = await provider.complete(chat)
    except BaseException as e:  # 上流の失敗もキャンセルも：払い戻してから、そのまま上へ流す
        await release_after_failure(limiter, reservation, e, clock.now())
        raise
    await settle(limiter, reservation, usage_tokens(result.usage))
    state = await limiter.quota_state(admission.user.id, admission.limits, now)
    for name, value in token_headers(state).items():
        response.headers[name] = value
    return AskOut(text=result.text, input_tokens=result.usage.input_tokens,
                  output_tokens=result.usage.output_tokens, used_today=state.used)


@dataclass
class HeldStream:
    """制限を通り、予約を取り、上流の最初のイベントまで読めたストリーム。"""

    admission: Admission
    reservation: Reservation
    primed: Primed


async def held_stream(body: ChatIn, admission: RateLimitDep, limiter: LimiterDep, settings: LimitSettingsDep,
                      clock: ClockDep, provider: ProviderDep) -> HeldStream:
    """ストリームを始める前の関門。ここで失敗すれば、まだ 200 を返していないので JSON のエラー本文になる。"""
    chat = build_chat(body)
    now = clock.now()
    await check_upstream_cooldown(limiter, now)
    reservation = await reserve_tokens(limiter, admission, reservation_amount(chat), now, settings)
    try:
        primed = await prime(provider, chat)
    except BaseException as e:
        await release_after_failure(limiter, reservation, e, clock.now())
        raise
    return HeldStream(admission, reservation, primed)


@app.post("/api/chat/stream", response_class=EventSourceResponse)
async def chat_stream(request: Request, held: Annotated[HeldStream, Depends(held_stream)],
                      limiter: LimiterDep) -> AsyncIterator[ServerSentEvent]:
    outcome = StreamOutcome(request_id=request.state.request_id, message_id=str(uuid7()),
                            input_estimate=estimate_input_tokens(held.primed.chat))
    async with aclosing(settled_events(request, held.primed, outcome, limiter, held.reservation)) as events:
        async for ev in events:
            yield ev
