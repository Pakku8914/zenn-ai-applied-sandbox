"""Session 14：構造化ログとリクエストID。1件の失敗を、request_id から上流の request-id とジョブまで追う。

事前に：docker compose restart worker（tasks.py を worker に読み込ませる）
起動：APP_MODULE=src.session14.app:app docker compose up -d --wait api

- POST /api/ask             … 1回の LLM 呼び出し（ログに上流の request-id と usage）
- POST /api/ask/stream      … 同じものを SSE で（ログはストリームが終わったときに1行）
- POST /api/jobs/plan-week  … ジョブを積む（request_id は Celery のヘッダで worker へ）
- GET  /api/jobs/{job_id}   … ジョブの状態
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import anthropic
import anyio
import httpx2
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from ulid import ULID
from uuid_utils import uuid7

from kondate.cache import make_redis
from kondate.clock import Clock, SystemClock

from .errors import MESSAGES, ApiError, install_error_handlers, translate
from .jsonlog import setup_json_logging
from .llm import LLMConfig, LogSettings, OpenedStream, ask, log_call, make_client, open_stream
from .logctx import request_id_var
from .middleware import RequestIdMiddleware
from .runner import create_job, delete_job, load_job
from .tasks import plan_week

logger = logging.getLogger("kondate.session14.jobs")
router = APIRouter()


# ---------------------------------------------------------------- 依存関数（モジュール直下に置く）


def get_llm(request: Request) -> AsyncAnthropic:
    return request.app.state.llm


def get_cfg(request: Request) -> LLMConfig:
    return request.app.state.cfg


def get_log_settings(request: Request) -> LogSettings:
    return request.app.state.log


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_clock() -> Clock:
    return SystemClock()


LLMDep = Annotated[AsyncAnthropic, Depends(get_llm)]
CfgDep = Annotated[LLMConfig, Depends(get_cfg)]
LogDep = Annotated[LogSettings, Depends(get_log_settings)]
RedisDep = Annotated[Redis, Depends(get_redis)]
ClockDep = Annotated[Clock, Depends(get_clock)]


def get_mock_headers(request: Request, cfg: CfgDep) -> dict[str, str]:
    """障害注入用の x-mock-* だけを上流へ渡す。接続先が mockllm でなければ常に空。"""
    if not cfg.forwards_mock_headers:
        return {}
    return {k: v for k, v in request.headers.items() if k.startswith("x-mock-")}


MockDep = Annotated[dict[str, str], Depends(get_mock_headers)]


# ---------------------------------------------------------------- 入出力


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)


class AskOut(BaseModel):
    answer: str
    stop_reason: str | None
    request_id: str


class PlanWeekIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(default=3, ge=1, le=7)


class JobAccepted(BaseModel):
    job_id: str
    status: str


class JobOut(BaseModel):
    job_id: str
    status: str
    done: int
    total: int
    result: dict | None
    error: dict | None


def sse(name: str, payload: dict) -> ServerSentEvent:
    return ServerSentEvent(event=name, raw_data=json.dumps(payload, ensure_ascii=False))


# ---------------------------------------------------------------- ルート


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/api/ask")
async def ask_route(body: AskIn, request: Request, llm: LLMDep, cfg: CfgDep, log: LogDep,
                    mock: MockDep) -> AskOut:
    try:
        answer = await ask(llm, cfg, log, body.question, extra_headers=mock)
    except anthropic.APIError as exc:
        raise translate(exc) from exc  # ログは ask() が残した。クライアントには固定文と request_id だけ
    return AskOut(answer=answer.text, stop_reason=answer.stop_reason, request_id=request.state.request_id)


async def opened_stream(body: AskIn, llm: LLMDep, cfg: CfgDep, log: LogDep, mock: MockDep) -> OpenedStream:
    """依存関数の中で上流を開く。開始前の失敗は ApiError になり、JSON のエラー本文で返る（Session 6）。"""
    try:
        return await open_stream(llm, cfg, log, body.question, extra_headers=mock)
    except anthropic.APIError as exc:
        raise translate(exc) from exc


@router.post("/api/ask/stream", response_class=EventSourceResponse)
async def ask_stream(opened: Annotated[OpenedStream, Depends(opened_stream)]) -> AsyncIterator[ServerSentEvent]:
    usage = {"input_tokens": 0, "output_tokens": 0}
    stop_reason: str | None = None
    outcome, error = "cancelled", None  # 最後まで読めずに終わった（切断された）ときの値
    try:
        yield sse("start", {"message_id": str(uuid7())})
        async for event in opened.stream:
            if event.type == "message_start":
                usage["input_tokens"] = event.message.usage.input_tokens
            elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                yield sse("delta", {"text": event.delta.text})
            elif event.type == "message_delta":
                usage["output_tokens"] = event.usage.output_tokens
                stop_reason = event.delta.stop_reason
        yield sse("usage", usage)
        yield sse("done", {"stop_reason": stop_reason})
        outcome = "ok"
    except (anthropic.APIError, httpx2.HTTPError) as exc:
        outcome, error = "error", type(exc).__name__
        type_ = translate(exc).type if isinstance(exc, anthropic.APIError) else "upstream_unavailable"
        # ジェネレータの中でも contextvars の request_id が読める（ミドルウェアの中で作られたタスクだから）
        yield sse("error", {"type": type_, "message": MESSAGES[type_], "request_id": request_id_var.get()})
    finally:
        with anyio.CancelScope(shield=True):
            await opened.stream.close()
        more: dict[str, object] = {"stop_reason": stop_reason, **usage}
        if error is not None:
            more["error"] = error
        log_call(opened.fields, outcome, opened.started, **more)


@router.post("/api/jobs/plan-week", status_code=202)
async def create_plan_week(body: PlanWeekIn, response: Response, redis: RedisDep, clock: ClockDep,
                           mock: MockDep) -> JobAccepted:
    job_id = f"job_{ULID.from_datetime(clock.now())}"
    await create_job(redis, job_id, total=body.days, mock_headers=mock)
    try:
        # apply_async は同期なのでスレッドで呼ぶ。asyncio.to_thread は contextvars を引き継ぐので、
        # before_task_publish（attach_request_id）がいまの request_id を読める
        await asyncio.to_thread(plan_week.apply_async, args=[job_id], task_id=job_id)
    except Exception:
        await delete_job(redis, job_id)  # 積めなかったジョブを queued のまま残さない
        raise
    logger.info("job_enqueued", extra={"job_id": job_id, "total": body.days})
    response.headers["Location"] = f"/api/jobs/{job_id}"
    return JobAccepted(job_id=job_id, status="queued")


@router.get("/api/jobs/{job_id}")
async def get_job(job_id: str, redis: RedisDep) -> JobOut:
    job = await load_job(redis, job_id)
    if job is None:
        raise ApiError(404, "not_found")
    return JobOut(**job)


# ---------------------------------------------------------------- アプリ


def create_app(cfg: LLMConfig | None = None, log: LogSettings | None = None, *,
               configure_logging: bool = True, trust_incoming: bool = True) -> FastAPI:
    cfg = cfg or LLMConfig()
    log = log or LogSettings()
    if configure_logging:
        setup_json_logging("kondate.session14")  # 標準出力へ JSON 1行（docker compose logs api で読める）

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.llm = make_client(cfg)
        app.state.redis = make_redis()
        try:
            yield
        finally:
            await app.state.llm.close()
            await app.state.redis.aclose()

    app = FastAPI(title="こんだてAI（構造化ログ）", lifespan=lifespan)
    app.state.cfg, app.state.log = cfg, log
    install_error_handlers(app)
    app.add_middleware(RequestIdMiddleware, trust_incoming=trust_incoming)
    app.include_router(router)
    return app


app = create_app()
