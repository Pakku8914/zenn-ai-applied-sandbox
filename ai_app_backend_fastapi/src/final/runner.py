"""final.plan_week の本体（worker の中で動く）。session12/runner.py のコピー。

ログはこのモジュールのロガー（kondate.final.runner）に出す。request_id と job_id は、Celery のシグナル
（celery_context.py）が contextvars に入れたものを、JSON のフォーマッタが自動で載せる。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from kondate.cache import make_redis

from .middleware import INTERNAL_ERROR_MESSAGE
from .planner import find_user, plan_day
from .store import NOT_RUNNING, JobStore

logger = logging.getLogger("kondate.final.runner")

MAX_RETRIES = 3
BACKOFF_BASE = 2.0
BACKOFF_CAP = 60.0

Sleep = Callable[[float], Awaitable[None]]
DayPlanner = Callable[[dict, int, date], dict]


class TransientJobError(Exception):
    """時間をおけば成功しうる失敗。"""


TRANSIENT: tuple[type[BaseException], ...] = (TransientJobError, RedisConnectionError, RedisTimeoutError, TimeoutError)


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    countdown: float | None = None


def decide(exc: BaseException, retries: int, *, rand: Callable[[], float] = random.random) -> RetryDecision:
    if isinstance(exc, TRANSIENT) and retries < MAX_RETRIES:
        ceiling = min(BACKOFF_CAP, BACKOFF_BASE * 2 ** retries)
        return RetryDecision(True, ceiling * (0.5 + rand() / 2))
    return RetryDecision(False)


async def run_plan(store: JobStore, job_id: str, *, sleep: Sleep = asyncio.sleep,
                   day_planner: DayPlanner = plan_day) -> str | None:
    job = await store.get(job_id)
    if job is None:
        return None
    status = await store.start(job_id)
    if status != "running":
        return status
    user = find_user(job.user_id)
    start = date.fromisoformat(job.start_date)
    recorded = await store.recorded_days(job_id)
    for i in range(job.total):
        if await store.cancel_requested(job_id):
            return await store.finish(job_id, "cancelled", "", job.result_ttl)
        if i in recorded:
            continue
        await sleep(job.work_seconds)
        if await store.advance(job_id, i, day_planner(user, i, start)) == NOT_RUNNING:
            return await store.status(job_id)
    days = await store.recorded_days(job_id)
    result = {"days": [days[i] for i in range(job.total)]}
    return await store.finish(job_id, "succeeded", json.dumps(result, ensure_ascii=False), job.result_ttl)


async def execute(job_id: str, *, retries: int, sleep: Sleep = asyncio.sleep, day_planner: DayPlanner = plan_day,
                  rand: Callable[[], float] = random.random) -> float | None:
    redis = make_redis()
    store = JobStore(redis)
    try:
        try:
            status = await run_plan(store, job_id, sleep=sleep, day_planner=day_planner)
            logger.info("plan_week_finished", extra={"status": status})
            return None
        except Exception as exc:
            decision = decide(exc, retries, rand=rand)
            if decision.retry:
                logger.warning("plan_week_retry", extra={"retries": retries, "countdown": decision.countdown,
                                                         "exc_type": type(exc).__name__})
                return decision.countdown
            logger.error("plan_week_failed", extra={"retries": retries}, exc_info=exc)
            job = await store.get(job_id)
            if job is not None:
                error = {"type": "internal_error", "message": INTERNAL_ERROR_MESSAGE, "request_id": job.request_id}
                await store.finish(job_id, "failed", json.dumps(error, ensure_ascii=False), job.result_ttl)
            return None
    finally:
        await redis.aclose()
