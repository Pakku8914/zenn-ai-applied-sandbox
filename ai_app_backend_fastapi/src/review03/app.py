"""復習3（問題2・問題4）：認証・レート制限・冪等キー・ジョブキューをつないだ、1週間の献立ジョブの API。

この章のアプリは api に載せず、検証の中（httpx2.ASGITransport で同一プロセス）だけで動かす。
worker 側（runner.execute_once）も検証で直接呼ぶ。tasks.py は置かない
（worker は src/*/tasks.py をすべて読むので、復習の試作が全セッションの worker を巻き込まないように）。

- POST /api/jobs/plan-week        … 認証 → レート制限 → 冪等キー → 記録してから積む → 202
- GET  /api/jobs/{job_id}         … 自分のジョブだけ（他人・期限切れは 404）
- GET  /api/jobs/{job_id}/events  … 進捗の SSE（Last-Event-ID の続きから）
- GET  /api/usage                 … ジョブで使ったトークンも含めた、その日の使用量
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated

import anyio
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from ulid import ULID

from kondate.cache import make_redis
from kondate.clock import JST, Clock
from kondate.db import engine
from kondate.worker import app as celery_app

from .auth import ClockDep, CurrentUserDep
from .errors import IN_PROGRESS_MESSAGE, ApiError, install_error_handlers
from .idempotency import KEY_PATTERN, IdempotencyStore, fingerprint
from .ratelimit import LimiterDep, LimitSettingsDep, RateLimitDep, get_redis, usage_today
from .store import TERMINAL, TERMINAL_EVENTS, JobRecord, JobStore

TASK_NAME = "review03.plan_week"
STREAM_ID = re.compile(r"\d+-\d+")
BLOCK_MS = 5000

Enqueue = Callable[[str], Awaitable[None]]


class JobSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REVIEW03_", extra="ignore")

    result_ttl_seconds: int = 3600  # 終わったジョブを残す時間
    pending_ttl_seconds: int = 86_400  # 終わる前のジョブを残す上限


def get_job_settings() -> JobSettings:
    return JobSettings()


async def send_to_worker(job_id: str) -> None:
    """本番の積み方（session12 と同じく task_id は job_id）。この章では tasks.py を置かないので、検証では差し替える。"""
    await asyncio.to_thread(celery_app.send_task, TASK_NAME, args=[job_id], task_id=job_id)


def get_enqueue() -> Enqueue:
    return send_to_worker


def get_store(redis: Annotated[Redis, Depends(get_redis)]) -> JobStore:
    return JobStore(redis)


def get_idempotency(redis: Annotated[Redis, Depends(get_redis)]) -> IdempotencyStore:
    return IdempotencyStore(redis)


JobSettingsDep = Annotated[JobSettings, Depends(get_job_settings)]
StoreDep = Annotated[JobStore, Depends(get_store)]
IdemDep = Annotated[IdempotencyStore, Depends(get_idempotency)]
EnqueueDep = Annotated[Enqueue, Depends(get_enqueue)]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    redis = make_redis()
    app.state.redis = redis
    try:
        yield
    finally:
        await redis.aclose()
        await engine.dispose()


app = FastAPI(title="こんだてAI（復習3：認証・制限・冪等キー・ジョブ）", lifespan=lifespan)
install_error_handlers(app)


class PlanWeekIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(default=7, ge=1, le=14)


class JobAccepted(BaseModel):
    job_id: str
    status: str


class JobOut(BaseModel):
    job_id: str
    status: str
    done: int
    total: int
    cancel_requested: bool
    result: dict | None
    error: dict | None


def new_job(user_id: str, days: int, clock: Clock, settings: JobSettings, request_id: str) -> JobRecord:
    """登録するジョブ。ID の時刻も献立の初日も、注入した時計から決める。"""
    now = clock.now()
    return JobRecord(
        job_id=f"job_{ULID.from_datetime(now)}", user_id=user_id, status="queued", done=0, total=days,
        start_date=(now.astimezone(JST).date() + timedelta(days=1)).isoformat(),  # 明日から
        work_seconds=0.0, result_ttl=settings.result_ttl_seconds, request_id=request_id,
        created_at=now.isoformat())


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/jobs/plan-week", status_code=202)
async def create_plan_week(request: Request, response: Response, body: PlanWeekIn, admission: RateLimitDep,
                           store: StoreDep, idem: IdemDep, enqueue: EnqueueDep, clock: ClockDep,
                           settings: JobSettingsDep,
                           idempotency_key: Annotated[str | None, Header()] = None) -> JobAccepted:
    user = admission.user  # 認証（S09）とレート制限（S10）は依存関数の中で済んでいる
    ticket = None
    if idempotency_key is not None:
        if not KEY_PATTERN.match(idempotency_key):
            raise ApiError(422, "invalid_request", "Idempotency-Key の形式が正しくありません")
        fp = fingerprint(request.method, request.url.path, body.model_dump())
        begun = await idem.begin(user.id, idempotency_key, fp)  # scope は利用者 ID（S11）
        if begun.outcome == "conflict":
            raise ApiError(409, "idempotency_conflict")
        if begun.outcome == "in_progress":
            raise ApiError(409, "idempotency_conflict", IN_PROGRESS_MESSAGE, headers={"retry-after": "1"})
        if begun.outcome == "replay" and begun.saved is not None:
            accepted = JobAccepted.model_validate_json(begun.saved.body)  # 新しいジョブは作らない
            response.status_code = begun.saved.status
            response.headers["idempotent-replayed"] = "true"
            response.headers["Location"] = f"/api/jobs/{accepted.job_id}"
            return accepted
        ticket = begun.ticket
    job = new_job(user.id, body.days, clock, settings, request.state.request_id)
    try:
        await store.create(job, ttl=settings.pending_ttl_seconds)  # 先に記録してから積む（S12）
        try:
            await enqueue(job.job_id)
        except BaseException:
            await store.delete(job.job_id)  # 積めなかったジョブを queued のまま残さない
            raise
    except BaseException:
        if ticket is not None:  # 失敗は保存しない。同じキーでやり直せるようにする（S11）
            with anyio.CancelScope(shield=True):
                await idem.abandon(ticket)
        raise
    accepted = JobAccepted(job_id=job.job_id, status=job.status)
    if ticket is not None:
        await idem.complete(ticket, 202, accepted.model_dump_json(), None)
    response.headers["Location"] = f"/api/jobs/{job.job_id}"
    return accepted


async def owned_job(job_id: str, user: CurrentUserDep, store: StoreDep) -> JobRecord:
    """自分のジョブだけを返す。比べるのは利用者 ID（どのキーで登録したかは見ない）。他人も期限切れも同じ 404。"""
    job = await store.get(job_id)
    if job is None or job.user_id != user.id:
        raise ApiError(404, "not_found")
    return job


OwnedJobDep = Annotated[JobRecord, Depends(owned_job)]


@app.get("/api/jobs/{job_id}")
async def get_job(job: OwnedJobDep) -> JobOut:
    return JobOut(job_id=job.job_id, status=job.status, done=job.done, total=job.total,
                  cancel_requested=job.cancel_requested, result=job.result, error=job.error)


@app.get("/api/jobs/{job_id}/events", response_class=EventSourceResponse)
async def job_events(request: Request, job: OwnedJobDep, store: StoreDep,
                     last_event_id: Annotated[str | None, Header()] = None) -> AsyncIterator[ServerSentEvent]:
    after = last_event_id if last_event_id and STREAM_ID.fullmatch(last_event_id) else "0-0"
    while not await request.is_disconnected():
        batch = await store.read_events(job.job_id, after, block_ms=BLOCK_MS)
        if not batch:
            current = await store.get(job.job_id)
            if current is None:
                return
            if current.status in TERMINAL:
                batch = await store.read_events(job.job_id, after)
                if not batch:
                    return
        for ev in batch:
            after = ev.id
            yield ServerSentEvent(event=ev.event, raw_data=ev.data, id=ev.id)
            if ev.event in TERMINAL_EVENTS:
                return


@app.get("/api/usage")
async def get_usage(user: CurrentUserDep, limiter: LimiterDep, settings: LimitSettingsDep, clock: ClockDep) -> dict:
    return await usage_today(limiter, user, settings, clock.now())
