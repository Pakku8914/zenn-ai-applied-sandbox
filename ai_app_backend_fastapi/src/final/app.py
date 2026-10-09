"""最終プロジェクト：こんだてAI バックエンド（API契約④）。②（Next.js＋AI SDK 7）の最終プロジェクトがこの API に接続する。

事前に（api コンテナの /app で）：
  docker compose restart worker                          … tasks.py（final.plan_week）を worker に読み込ませる
  docker compose exec api python -m src.final.cli setup  … マイグレーションと5人の登録
  docker compose exec api python -m src.final.cli issue u001
起動：APP_MODULE=src.final.app:app docker compose up -d --wait api

- POST   /api/chat                     … UI Message Stream（AI SDK の DefaultChatTransport の本文をそのまま受ける）
- GET    /api/chat/{id}/stream         … 常に 204（ストリームの再開はしない）
- GET    /api/conversations            … 自分の会話の一覧
- GET    /api/conversations/{id}       … UIMessage[]（他人の会話は 404）
- POST   /api/jobs/plan-week ほか      … 1週間の献立ジョブ（jobs.py）
- GET    /api/usage                    … {plan, used_today, limit_today, requests_per_minute}
- GET    /health・/ready               … liveness・readiness
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

import anthropic
import httpx2
from fastapi import APIRouter, Depends, FastAPI, Path, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from kondate.cache import make_redis
from kondate.db import engine
from kondate.settings import get_settings

from . import chat, jobs, repo
from .aggregate import used_today
from .auth import CurrentUserDep
from .deps import ClockDep, SessionDep
from .errors import ApiError, install_error_handlers
from .fallback import FallbackHeaderMiddleware, Route
from .jsonlog import setup_json_logging
from .lifecycle import Drain, StreamGate, install_drain_signals
from .middleware import RequestIdMiddleware
from .probes import ReadinessProbe, build_checks
from .providers import AnthropicProvider
from .ratelimit import LimitSettingsDep
from .retry import RetryPolicy
from .settings import FinalSettings
from .uimessages import to_ui_messages

logger = logging.getLogger("kondate.final.app")
router = APIRouter()

ChatIdPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


def build_routes(client: anthropic.AsyncAnthropic, settings: FinalSettings) -> list[Route]:
    """primary（チャット用のモデル）→ light（軽い処理用のモデル）。openai を足すなら Session 11 の版を参照。"""
    base = get_settings()
    provider = AnthropicProvider(client, default_model=base.llm_model)
    policy = RetryPolicy(max_attempts=settings.max_attempts)
    return [Route("primary", provider, None, policy), Route("light", provider, base.llm_model_light, policy)]


def get_probe(request: Request) -> ReadinessProbe:
    return request.app.state.probe


class ConversationOut(BaseModel):
    id: str  # AI SDK の chatId（POST /api/chat の本文の id と同じ値）
    title: str | None
    created_at: datetime
    updated_at: datetime


class UsageOut(BaseModel):
    plan: str
    used_today: int
    limit_today: int
    requests_per_minute: int


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request, probe: Annotated[ReadinessProbe, Depends(get_probe)]) -> JSONResponse:
    if request.app.state.drain.started:
        return JSONResponse({"status": "draining", "checks": {}}, status_code=503)
    checks = await probe.run()
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)


@router.get("/api/conversations")
async def list_conversations(user: CurrentUserDep, session: SessionDep) -> list[ConversationOut]:
    rows = await repo.list_conversations(session, user.id)
    return [ConversationOut(id=c.chat_id, title=c.title, created_at=c.created_at, updated_at=c.updated_at)
            for c in rows]


@router.get("/api/conversations/{chat_id}")
async def show_conversation(chat_id: ChatIdPath, user: CurrentUserDep, session: SessionDep) -> list[dict]:
    conv = await repo.find_conversation(session, user.id, chat_id)
    if conv is None:
        raise ApiError(404, "not_found")  # 他人の会話も「無い」と同じ 404（存在を教えない）
    return to_ui_messages(await repo.load_messages(session, conv.id))


@router.get("/api/usage")
async def get_usage(user: CurrentUserDep, session: SessionDep, settings: LimitSettingsDep,
                    clock: ClockDep) -> UsageOut:
    limits = settings.for_plan(user.plan)
    return UsageOut(plan=user.plan, used_today=await used_today(session, user.id, clock.now()),
                    limit_today=limits.tokens_per_day, requests_per_minute=limits.requests_per_minute)


def create_app(settings: FinalSettings | None = None, *, configure_logging: bool = True) -> FastAPI:
    settings = settings or FinalSettings()
    if configure_logging:
        setup_json_logging("kondate.final")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        restore_signals = install_drain_signals(app.state.drain)
        redis = make_redis()
        http = httpx2.AsyncClient(timeout=settings.ready_timeout_seconds)
        # 接続先とキーは ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から。SDK の自動リトライは 0（Session 11 の層だけで再試行）
        client = anthropic.AsyncAnthropic(timeout=anthropic.Timeout(settings.llm_timeout_seconds, connect=5.0),
                                          max_retries=0)
        app.state.redis = redis
        app.state.routes = build_routes(client, settings)
        mock_url = settings.anthropic_base_url.rstrip("/") if settings.upstream_is_mock else None
        app.state.probe = ReadinessProbe(build_checks(engine, redis, http, mock_url=mock_url),
                                         settings.ready_timeout_seconds)
        try:
            yield
        finally:
            restore_signals()
            app.state.drain.cancel_timer()
            await client.close()
            await http.aclose()
            await redis.aclose()
            await engine.dispose()

    app = FastAPI(title="こんだてAI バックエンド（最終プロジェクト）", lifespan=lifespan)
    app.state.settings = settings
    app.state.drain = Drain(settings.drain_grace_seconds)
    app.state.gate = StreamGate(settings.max_streams_per_worker)
    app.state.outcomes = deque(maxlen=100)  # 直近の往復の結末（検証で見る）
    install_error_handlers(app)
    app.add_middleware(FallbackHeaderMiddleware)
    app.add_middleware(RequestIdMiddleware, trust_incoming=settings.trust_request_id)
    # 最後に足したものが一番外側。エラーの応答にも CORS のヘッダが付くよう、CORS を外側に置く
    app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "x-request-id"],
                       expose_headers=["x-request-id", "retry-after", "x-kondate-fallback",
                                       "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
                                       "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens"])
    app.include_router(router)
    app.include_router(chat.router)
    app.include_router(jobs.router)
    return app


app = create_app()
