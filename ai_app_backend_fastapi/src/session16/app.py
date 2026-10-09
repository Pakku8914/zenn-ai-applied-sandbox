"""Session 16：本番で落ちない・止められる構成（liveness と readiness・設定の検証・graceful shutdown）。

本番イメージで動かす：docker compose --profile prod up -d --build --wait api-prod（ホストの 8719）
開発の api で動かす：APP_MODULE=src.session16.app:app docker compose up -d --wait api（ホストの 8710）

- GET  /health           … liveness：このプロセスが応答できるか（依存先は見ない。drain 中も 200）
- GET  /ready            … readiness：依存先（PostgreSQL・Redis・mockllm）に届くか。drain 中は 503
- POST /api/chat/stream  … 自前の SSE（API契約③）。drain 中・満員なら、始める前に 503 service_unavailable

認証・レート制限・課金計測は外している（止め方に集中するため。最終プロジェクトで組み合わせる）。
"""

from __future__ import annotations

import logging
import os
from collections import deque
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager

import anthropic
import httpx2
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uuid_utils import uuid7

from .config import ProdSettings, load_settings_or_exit
from .errors import ApiError, install_error_handlers
from .jsonlog import setup_json_logging
from .lifecycle import Drain, StreamGate, install_drain_signals
from .middleware import RequestIdMiddleware
from .probes import ReadinessProbe, build_checks
from .relay import StreamOutcome, anthropic_events, relay

logger = logging.getLogger("kondate.session16.app")
router = APIRouter()


def make_client(settings: ProdSettings) -> AsyncAnthropic:
    return AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value(),
                          base_url=settings.anthropic_base_url,
                          timeout=anthropic.Timeout(settings.llm_timeout_seconds, connect=5.0),
                          max_retries=0)  # 再試行は Session 11 の retry_call に集約する


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------- 依存関数（モジュール直下に置く）


def forwarded_mock_headers(request: Request) -> dict[str, str]:
    """遅延・障害注入の x-mock-* だけを上流へ渡す。接続先が mockllm のときだけ（本物の API には渡さない）。"""
    if not request.app.state.settings.upstream_is_mock:
        return {}
    return {k: v for k, v in request.headers.items() if k.startswith("x-mock-")}


def admit_stream(request: Request) -> None:
    """ストリームを始める前の関所。ここで断れば、まだ 200 を返していないので JSON のエラー本文で返せる。"""
    state = request.app.state
    if state.drain.started or state.gate.full:
        # どちらも「別のサーバーなら受けられる」状態。少し待ってやり直してもらう（LB が別の行き先を選ぶ）
        raise ApiError(503, "service_unavailable", {"retry-after": "1"})


# ---------------------------------------------------------------- ルート


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    state = request.app.state
    if state.drain.started:  # 止まり始めたら、依存先が元気でも「もう送らないで」と答える
        return JSONResponse({"status": "draining", "checks": {}}, status_code=503)
    checks = await state.probe.run()
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks},
                        status_code=200 if ok else 503)


@router.post("/api/chat/stream", response_class=EventSourceResponse, dependencies=[Depends(admit_stream)])
async def chat_stream(body: ChatIn, request: Request) -> AsyncIterator[ServerSentEvent]:
    state = request.app.state
    outcome = StreamOutcome(request_id=request.state.request_id, message_id=str(uuid7()))
    source = anthropic_events(state.llm, state.settings, body.message, forwarded_mock_headers(request))
    events = relay(source, outcome=outcome, drain=state.drain, gate=state.gate, on_close=state.outcomes.append)
    async with aclosing(events):
        async for ev in events:
            yield ev


# ---------------------------------------------------------------- 計測用のヘッダ


class WorkerPidHeader:
    """応答ヘッダ x-kondate-worker にプロセス ID を載せる（EXPOSE_WORKER_PID=true のときだけ。本番では付けない）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        pid = str(os.getpid())

        async def send_with_pid(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["x-kondate-worker"] = pid
            await send(message)

        await self.app(scope, receive, send_with_pid)


# ---------------------------------------------------------------- アプリ


def create_app(settings: ProdSettings | None = None, *, configure_logging: bool = True) -> FastAPI:
    if settings is None:
        settings = load_settings_or_exit()
    if configure_logging:
        setup_json_logging("kondate.session16")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 接続はワーカー（プロセス）ごとに、そのプロセスのイベントループの中で作る
        restore_signals = install_drain_signals(app.state.drain)
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        http = httpx2.AsyncClient(timeout=settings.ready_timeout_seconds)
        app.state.llm = make_client(settings)
        app.state.probe = ReadinessProbe(build_checks(settings, engine, redis, http), settings.ready_timeout_seconds)
        logger.info("worker_started", extra={"pid": os.getpid()})
        try:
            yield
        finally:
            # ここに来るのは、uvicorn が配信中の接続を待ち終えた（または打ち切った）後
            restore_signals()
            app.state.drain.cancel_timer()
            await app.state.llm.close()
            await http.aclose()
            await redis.aclose()
            await engine.dispose()
            logger.info("worker_stopped", extra={"pid": os.getpid()})

    app = FastAPI(title="こんだてAI（本番設定）", lifespan=lifespan)
    app.state.settings = settings
    app.state.drain = Drain(settings.drain_grace_seconds)
    app.state.gate = StreamGate(settings.max_streams_per_worker)
    app.state.outcomes = deque(maxlen=100)  # 直近のストリームの結末（検証で見る）
    install_error_handlers(app)
    if settings.expose_worker_pid:
        app.add_middleware(WorkerPidHeader)
    app.add_middleware(RequestIdMiddleware)  # 最後に足したものが一番外側。想定外の例外もここで 500 にする
    app.include_router(router)
    return app


app = create_app()
