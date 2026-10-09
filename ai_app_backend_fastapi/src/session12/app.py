"""Session 12：1週間の献立づくり（plan_week）をジョブキューで実行し、進捗を SSE で届け、キャンセルできるようにする。

事前に（api コンテナの /app で）：
  docker compose restart worker                          … tasks.py を worker に読み込ませる
  docker compose exec api python -m src.session12.cli setup
  docker compose exec api python -m src.session12.cli issue u002
起動：APP_MODULE=src.session12.app:app docker compose up -d --wait api

- POST   /api/jobs/plan-week        … ジョブを登録して 202 と job_id を返す（処理の終わりは待たない）
- GET    /api/jobs/{job_id}         … 状態・進捗・結果
- GET    /api/jobs/{job_id}/events  … 進捗の SSE（progress {done, total} → done {result}）
- DELETE /api/jobs/{job_id}         … キャンセル（キュー待ちはその場で、実行中は中止フラグで）
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated

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
from .errors import ApiError, install_error_handlers
from .store import TERMINAL, TERMINAL_EVENTS, JobRecord, JobStore
from .tasks import plan_week

STREAM_ID = re.compile(r"\d+-\d+")  # Redis ストリームの ID（Last-Event-ID として戻ってくる）
BLOCK_MS = 5000  # 新しいイベントを待つ最長の時間。この間隔で切断と期限切れを確かめる


class JobSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="S12_", extra="ignore")

    work_seconds: float = 1.0  # 1日分の処理にかける時間（LLM 呼び出しの代役。verify では短くする）
    result_ttl_seconds: int = 3600  # 終わったジョブを残す時間
    pending_ttl_seconds: int = 86_400  # 終わる前のジョブを残す上限（worker が消えても残り続けないように）


def get_job_settings() -> JobSettings:
    return JobSettings()


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_store(redis: Annotated[Redis, Depends(get_redis)]) -> JobStore:
    return JobStore(redis)


JobSettingsDep = Annotated[JobSettings, Depends(get_job_settings)]
StoreDep = Annotated[JobStore, Depends(get_store)]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    redis = make_redis()
    app.state.redis = redis
    try:
        yield
    finally:
        await redis.aclose()
        await engine.dispose()


app = FastAPI(title="こんだてAI（ジョブキュー）", lifespan=lifespan)
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


def job_out(job: JobRecord) -> JobOut:
    return JobOut(job_id=job.job_id, status=job.status, done=job.done, total=job.total,
                  cancel_requested=job.cancel_requested, result=job.result, error=job.error)


def new_job(user_id: str, days: int, clock: Clock, settings: JobSettings, request_id: str) -> JobRecord:
    """登録するジョブ。ID の時刻も献立の初日も、注入した時計から決める（datetime.now() を呼ばない）。"""
    now = clock.now()
    return JobRecord(
        job_id=f"job_{ULID.from_datetime(now)}", user_id=user_id, status="queued", done=0, total=days,
        start_date=(now.astimezone(JST).date() + timedelta(days=1)).isoformat(),  # 明日から
        work_seconds=settings.work_seconds, result_ttl=settings.result_ttl_seconds,
        request_id=request_id, created_at=now.isoformat())


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/jobs/plan-week", status_code=202)
async def create_plan_week(request: Request, response: Response, body: PlanWeekIn, user: CurrentUserDep,
                           store: StoreDep, clock: ClockDep, settings: JobSettingsDep) -> JobAccepted:
    job = new_job(user.id, body.days, clock, settings, request.state.request_id)
    await store.create(job, ttl=settings.pending_ttl_seconds)  # 先に記録してから積む
    try:
        # apply_async はブローカー（Redis）へ同期で書き込むので、イベントループを止めないようスレッドで呼ぶ
        await asyncio.to_thread(plan_week.apply_async, args=[job.job_id], task_id=job.job_id)
    except Exception:
        await store.delete(job.job_id)  # 積めなかったジョブを queued のまま残さない
        raise
    response.headers["Location"] = f"/api/jobs/{job.job_id}"
    return JobAccepted(job_id=job.job_id, status=job.status)


async def owned_job(job_id: str, user: CurrentUserDep, store: StoreDep) -> JobRecord:
    """自分のジョブだけを返す。他人のジョブも、期限切れのジョブも、同じ 404 にする（存在を教えない）。"""
    job = await store.get(job_id)
    if job is None or job.user_id != user.id:
        raise ApiError(404, "not_found")
    return job


OwnedJobDep = Annotated[JobRecord, Depends(owned_job)]


@app.get("/api/jobs/{job_id}")
async def get_job(job: OwnedJobDep) -> JobOut:
    return job_out(job)


@app.get("/api/jobs/{job_id}/events", response_class=EventSourceResponse)
async def job_events(request: Request, job: OwnedJobDep, store: StoreDep,
                     last_event_id: Annotated[str | None, Header()] = None) -> AsyncIterator[ServerSentEvent]:
    # 最初から送る（＝途中から購読しても progress 0 から届く）。再接続なら Last-Event-ID の続きから
    after = last_event_id if last_event_id and STREAM_ID.fullmatch(last_event_id) else "0-0"
    while not await request.is_disconnected():
        batch = await store.read_events(job.job_id, after, block_ms=BLOCK_MS)
        if not batch:
            current = await store.get(job.job_id)
            if current is None:
                return  # 保存期限が過ぎて消えた
            if current.status in TERMINAL:
                batch = await store.read_events(job.job_id, after)  # 待たずに残りを読む
                if not batch:
                    return  # 終わりのイベントまで送り済み
        for ev in batch:
            after = ev.id
            yield ServerSentEvent(event=ev.event, raw_data=ev.data, id=ev.id)
            if ev.event in TERMINAL_EVENTS:
                return


@app.delete("/api/jobs/{job_id}")
async def cancel_job(job: OwnedJobDep, store: StoreDep, response: Response) -> JobOut:
    await store.cancel(job.job_id, ttl=job.result_ttl)
    if job.status in ("queued", "running"):
        # まだ worker が受け取っていない配送を捨てさせる。実行中のタスクは止めない（terminate しない）
        await asyncio.to_thread(celery_app.control.revoke, job.job_id)
    current = await store.get(job.job_id)
    if current is None:
        raise ApiError(404, "not_found")
    if current.status == "running":
        response.status_code = 202  # 止める指示は受け付けた。止まるのは worker が次の日の区切りで気づいたとき
    return job_out(current)
