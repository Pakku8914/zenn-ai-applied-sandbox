"""1週間の献立ジョブの HTTP API（session12/app.py のルートのコピー）と、ジョブを積む関数 enqueue_plan_week。

enqueue_plan_week は2か所から呼ぶ：POST /api/jobs/plan-week と、チャットのツール plan_week。
どちらも「先に Redis へ記録してから積む」「積めなかったら記録を消す」は同じにする（1か所に書く）。
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from ulid import ULID

from kondate.clock import JST, Clock
from kondate.worker import app as celery_app

from .auth import CurrentUserDep
from .deps import ClockDep
from .errors import ApiError
from .ratelimit import RedisDep
from .store import TERMINAL, TERMINAL_EVENTS, JobRecord, JobStore
from .tasks import plan_week

router = APIRouter()
STREAM_ID = re.compile(r"\d+-\d+")
BLOCK_MS = 5000


class JobSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOB_", extra="ignore")

    work_seconds: float = 1.0  # 1日分の処理にかける時間（LLM 呼び出しの代役。verify では短くする）
    result_ttl_seconds: int = 3600
    pending_ttl_seconds: int = 86_400


def get_job_settings() -> JobSettings:
    return JobSettings()


def get_store(redis: RedisDep) -> JobStore:
    return JobStore(redis)


JobSettingsDep = Annotated[JobSettings, Depends(get_job_settings)]
StoreDep = Annotated[JobStore, Depends(get_store)]


class PlanWeekIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # user_id を本文で受け取らない（持ち主は認証した利用者）

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


def job_out(job: JobRecord) -> JobOut:
    return JobOut(job_id=job.job_id, status=job.status, done=job.done, total=job.total,
                  cancel_requested=job.cancel_requested, result=job.result, error=job.error)


async def enqueue_plan_week(store: JobStore, *, user_id: str, days: int, clock: Clock, settings: JobSettings,
                            request_id: str) -> JobRecord:
    now = clock.now()
    job = JobRecord(
        job_id=f"job_{ULID.from_datetime(now)}", user_id=user_id, status="queued", done=0, total=days,
        start_date=(now.astimezone(JST).date() + timedelta(days=1)).isoformat(),
        work_seconds=settings.work_seconds, result_ttl=settings.result_ttl_seconds,
        request_id=request_id, created_at=now.isoformat())
    await store.create(job, ttl=settings.pending_ttl_seconds)
    try:
        # apply_async は同期なのでスレッドで呼ぶ（to_thread は contextvars を引き継ぐので、request_id がヘッダに載る）
        await asyncio.to_thread(plan_week.apply_async, args=[job.job_id], task_id=job.job_id)
    except Exception:
        await store.delete(job.job_id)
        raise
    return job


@router.post("/api/jobs/plan-week", status_code=202)
async def create_plan_week(request: Request, response: Response, body: PlanWeekIn, user: CurrentUserDep,
                           store: StoreDep, clock: ClockDep, settings: JobSettingsDep) -> JobAccepted:
    job = await enqueue_plan_week(store, user_id=user.id, days=body.days, clock=clock, settings=settings,
                                  request_id=request.state.request_id)
    response.headers["Location"] = f"/api/jobs/{job.job_id}"
    return JobAccepted(job_id=job.job_id, status=job.status)


async def owned_job(job_id: str, user: CurrentUserDep, store: StoreDep) -> JobRecord:
    """自分のジョブだけを返す。他人のジョブも、期限切れのジョブも、同じ 404 にする（存在を教えない）。"""
    job = await store.get(job_id)
    if job is None or job.user_id != user.id:
        raise ApiError(404, "not_found")
    return job


OwnedJobDep = Annotated[JobRecord, Depends(owned_job)]


@router.get("/api/jobs/{job_id}")
async def get_job(job: OwnedJobDep) -> JobOut:
    return job_out(job)


@router.get("/api/jobs/{job_id}/events", response_class=EventSourceResponse)
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


@router.delete("/api/jobs/{job_id}")
async def cancel_job(job: OwnedJobDep, store: StoreDep, response: Response) -> JobOut:
    await store.cancel(job.job_id, ttl=job.result_ttl)
    if job.status in ("queued", "running"):
        await asyncio.to_thread(celery_app.control.revoke, job.job_id)
    current = await store.get(job.job_id)
    if current is None:
        raise ApiError(404, "not_found")
    if current.status == "running":
        response.status_code = 202
    return job_out(current)
