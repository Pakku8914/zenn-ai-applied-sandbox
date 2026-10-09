"""トークン課金計測（usage を落とさず台帳に記録し、金額に換算し、予算を超えたら止める）。

事前に（api コンテナの /app で）：
  docker compose exec api alembic -c src/session13/alembic.ini upgrade head
  docker compose exec api python -m src.session13.cli seed-users
  docker compose exec api python -m src.session13.cli issue u001
起動：APP_MODULE=src.session13.app:app docker compose up -d --wait api

- GET  /api/usage        … {plan, used_today, limit_today, requests_per_minute}（used_today は台帳から）
- GET  /api/usage/daily  … 自分の日別の集計（トークン4種と金額）
- POST /api/ask          … 認証 → レート制限 → 予算 → 予約 → 上流 → 記録 → 精算
- POST /api/chat/stream  … SSE。usage を送る前に記録し、途中で終わったら見積もりを記録する
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, PlainSerializer
from pydantic_settings import BaseSettings, SettingsConfigDict
from uuid_utils import uuid7

from kondate.cache import make_redis
from kondate.db import engine
from kondate.settings import get_settings

from .aggregate import daily_usage, jst_date, usage_today
from .auth import ClockDep, CurrentUserDep
from .budget import BudgetDep
from .deps import FactoryDep, SessionDep
from .errors import install_error_handlers
from .inputs import ChatDep
from .limiter import Reservation
from .metering import Meter, UsageRecord, metered_events, priced, save_quietly
from .pricing import PriceTableDep
from .providers import LLMProvider, open_provider
from .ratelimit import (Admission, LimiterDep, LimitSettingsDep, RateLimitDep, check_upstream_cooldown,
                        release_after_failure, reservation_amount, reserve_tokens, settle, token_headers,
                        usage_tokens)
from .relay import Primed, StreamOutcome, estimate_input_tokens, prime


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    openai_model: str | None = None


def setup_logging() -> None:
    log = logging.getLogger("kondate.session13")
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
        async with open_provider(s.llm_provider, model=model, timeout=30.0, max_retries=0) as provider:
            app.state.provider, app.state.redis, app.state.model = provider, redis, model
            yield
    finally:
        await redis.aclose()
        await engine.dispose()


app = FastAPI(title="こんだてAI（トークン課金計測）", lifespan=lifespan)
install_error_handlers(app)


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


ProviderDep = Annotated[LLMProvider, Depends(get_provider)]

# Decimal は JSON で文字列にする（float にすると桁が化ける）。0E-8 のような指数表記にならないよう "f" で書く
Usd = Annotated[Decimal, PlainSerializer(lambda d: format(d, "f"), return_type=str)]


class UsageOut(BaseModel):
    plan: str
    used_today: int
    limit_today: int
    requests_per_minute: int


class DayUsageOut(BaseModel):
    day: str
    requests: int
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: Usd | None  # その日の行がすべて単価なしなら null（0 にしない）
    unpriced: int  # 金額の分からない行の数


class DailyOut(BaseModel):
    days: list[DayUsageOut]


class AskOut(BaseModel):
    text: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    cost_usd: Usd | None  # 単価表に無いモデルなら null


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/usage")
async def get_usage(user: CurrentUserDep, session: SessionDep, settings: LimitSettingsDep,
                    clock: ClockDep) -> UsageOut:
    return UsageOut(**await usage_today(session, user, settings.for_plan(user.plan), clock.now()))


@app.get("/api/usage/daily")
async def get_daily(user: CurrentUserDep, session: SessionDep, clock: ClockDep,
                    days: Annotated[int, Query(ge=1, le=31)] = 7) -> DailyOut:
    last = jst_date(clock.now())
    rows = await daily_usage(session, user.id, last - timedelta(days=days - 1), last)
    return DailyOut(days=[DayUsageOut(**{**asdict(r), "day": r.day.isoformat()}) for r in rows])


@app.post("/api/ask")
async def ask(request: Request, response: Response, chat: ChatDep, admission: RateLimitDep, budget: BudgetDep,
              limiter: LimiterDep, settings: LimitSettingsDep, clock: ClockDep, provider: ProviderDep,
              factory: FactoryDep, table: PriceTableDep) -> AskOut:
    # budget：予算を超える要求は、ここに来る前に 402 で断られている
    now = clock.now()
    await check_upstream_cooldown(limiter, now)
    reservation = await reserve_tokens(limiter, admission, reservation_amount(chat), now, settings)
    try:
        result = await provider.complete(chat)
    except BaseException as e:
        await release_after_failure(limiter, reservation, e, clock.now())
        raise
    record = UsageRecord(request.state.request_id, admission.user.id, chat.model or "", now, result.usage,
                         "upstream", "completed")
    try:
        await save_quietly(factory, record, table)  # 上流はもう課金している。記録できなくても答えは返す
    finally:
        await settle(limiter, reservation, usage_tokens(result.usage))
    state = await limiter.quota_state(admission.user.id, admission.limits, now)
    for name, value in token_headers(state).items():
        response.headers[name] = value
    u = result.usage
    return AskOut(text=result.text, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                  cache_read_input_tokens=u.cache_read_input_tokens,
                  cache_creation_input_tokens=u.cache_creation_input_tokens, cost_usd=priced(record, table)[0])


@dataclass
class HeldStream:
    """制限と予算を通り、予約を取り、上流の最初のイベントまで読めたストリーム。"""

    admission: Admission
    reservation: Reservation
    primed: Primed
    started_at: datetime


async def held_stream(chat: ChatDep, admission: RateLimitDep, budget: BudgetDep, limiter: LimiterDep,
                      settings: LimitSettingsDep, clock: ClockDep, provider: ProviderDep) -> HeldStream:
    """ストリームを始める前の関門。ここで失敗すれば、まだ 200 を返していないので JSON のエラー本文になる。"""
    now = clock.now()
    await check_upstream_cooldown(limiter, now)
    reservation = await reserve_tokens(limiter, admission, reservation_amount(chat), now, settings)
    try:
        primed = await prime(provider, chat)
    except BaseException as e:  # 上流が 200 で応じなかった：課金されないので台帳には書かない
        await release_after_failure(limiter, reservation, e, clock.now())
        raise
    return HeldStream(admission, reservation, primed, now)


@app.post("/api/chat/stream", response_class=EventSourceResponse)
async def chat_stream(request: Request, held: Annotated[HeldStream, Depends(held_stream)], limiter: LimiterDep,
                      factory: FactoryDep, table: PriceTableDep) -> AsyncIterator[ServerSentEvent]:
    outcome = StreamOutcome(request_id=request.state.request_id, message_id=str(uuid7()),
                            input_estimate=estimate_input_tokens(held.primed.chat))
    meter = Meter(factory, table, held.admission.user.id, held.primed.chat.model or "", held.started_at)
    async with aclosing(metered_events(request, held.primed, outcome, limiter, held.reservation, meter)) as events:
        async for ev in events:
            yield ev
