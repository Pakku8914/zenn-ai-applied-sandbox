"""復習4の練習用アプリ：1本の SSE に、フォールバック（S11）・課金計測（S13）・リクエストIDと JSON ログ（S14）・drain（S16）を重ねたもの。

- GET  /health
- POST /api/chat/stream … 自前の SSE（API契約③）。drain 中は始める前に 503 service_unavailable（retry-after: 1）

認証・レート制限・予算は外している（最終プロジェクトで組み合わせる）。利用者は get_user_id が決める（既定 u001）。
検証スクリプトは dependency_overrides で get_llm（ResilientLLM）と get_clock を差し替え、lifespan は動かさない。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from uuid_utils import uuid7

from kondate.cache import make_redis
from kondate.clock import Clock, SystemClock
from kondate.db import SessionLocal
from kondate.settings import get_settings

from .breaker import PREFIX
from .errors import ApiError, from_provider_error, install_error_handlers
from .fallback import FallbackHeaderMiddleware, ResilientLLM, Route, Served
from .jsonlog import setup_json_logging
from .lifecycle import Drain, install_drain_signals
from .metering import Meter, metered
from .middleware import RequestIdMiddleware
from .pricing import PriceTableDep
from .providers import ChatRequest, ProviderError, open_provider
from .relay import Primed, StreamOutcome, chat_for, estimate_input_tokens, relay

logger = logging.getLogger("kondate.review04.app")
router = APIRouter()

DEFAULT_USER = "u001"
DRAIN_GRACE_SECONDS = 5.0  # 演習用の小さな値（本番は ProdSettings の DRAIN_GRACE_SECONDS。セッション16）


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------- 依存関数（モジュール直下に置く）


def get_clock() -> Clock:
    return SystemClock()


def get_user_id() -> str:
    return DEFAULT_USER  # 認証は省略（最終プロジェクトでセッション9の CurrentUserDep に置き換える）


def get_llm(request: Request) -> ResilientLLM:
    return request.app.state.llm


ClockDep = Annotated[Clock, Depends(get_clock)]
UserDep = Annotated[str, Depends(get_user_id)]
LLMDep = Annotated[ResilientLLM, Depends(get_llm)]


def admit_stream(request: Request) -> None:
    """ストリームを始める前の関所。まだ 200 を返していないので JSON のエラー本文で断れる（セッション16）。"""
    if request.app.state.drain.started:
        raise ApiError(503, "service_unavailable", {"retry-after": "1"})


@dataclass
class Opened:
    """先読みまで済んだストリームと、台帳に書くための値。"""

    served: Served[Primed]
    chat: ChatRequest
    started_at: datetime  # 要求を受け付けた時刻（先読みのリトライで時計が進む前に取る）

    @property
    def model(self) -> str:
        """台帳に書くモデル＝実際に答えた経路のモデル（問題7）。設定の LLM_MODEL ではない。"""
        return self.served.value.chat.model or get_settings().llm_model


async def open_stream(body: ChatIn, request: Request, llm: LLMDep, clock: ClockDep,
                      _admitted: Annotated[None, Depends(admit_stream)]) -> Opened:
    """drain の関所 → 先読み（リトライ・フォールバック込み）。失敗はまだ JSON で返せる（セッション6・11）。"""
    started_at = clock.now()
    chat = chat_for(body.message)
    try:
        served = await llm.prime(chat)
    except ProviderError as e:
        logger.warning("upstream_failed", extra={"kind": e.kind, "provider": e.provider,
                                                 "upstream_request_id": e.request_id})
        raise from_provider_error(e) from None
    request.state.fallback = served.fallback  # FallbackHeaderMiddleware が x-kondate-fallback に載せる
    return Opened(served, chat, started_at)


OpenedDep = Annotated[Opened, Depends(open_stream)]


# ---------------------------------------------------------------- ルート


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/api/chat/stream", response_class=EventSourceResponse)
async def chat_stream(request: Request, opened: OpenedDep, user_id: UserDep,
                      table: PriceTableDep) -> AsyncIterator[ServerSentEvent]:
    outcome = StreamOutcome(request_id=request.state.request_id, message_id=str(uuid7()),
                            input_estimate=estimate_input_tokens(opened.chat))
    meter = Meter(SessionLocal, table, user_id, opened.model, opened.started_at)
    events = metered(relay(opened.served.value, outcome=outcome, drain=request.app.state.drain), outcome, meter)
    async with aclosing(events):
        async for ev in events:
            yield ev


# ---------------------------------------------------------------- アプリ


def create_app(*, trust_incoming: bool = False, configure_logging: bool = True) -> FastAPI:
    if configure_logging:
        setup_json_logging("kondate.review04")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = get_settings()
        restore_signals = install_drain_signals(app.state.drain)
        redis = make_redis()
        # 接続先とキーは環境変数 ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から（compose の既定は mockllm）
        async with open_provider("anthropic", model=settings.llm_model, max_retries=0, timeout=30.0) as provider:
            routes = [Route("primary", provider, settings.llm_model),
                      Route("light", provider, settings.llm_model_light)]
            app.state.llm = ResilientLLM(routes, redis=redis, clock=SystemClock(), prefix=PREFIX)
            try:
                yield
            finally:
                restore_signals()
                app.state.drain.cancel_timer()
                await redis.aclose()

    app = FastAPI(title="こんだてAI（復習4）", lifespan=lifespan)
    app.state.drain = Drain(DRAIN_GRACE_SECONDS)
    install_error_handlers(app)
    app.add_middleware(FallbackHeaderMiddleware)
    app.add_middleware(RequestIdMiddleware, trust_incoming=trust_incoming)  # 最後に足したものが一番外側
    app.include_router(router)
    return app


app = create_app()
