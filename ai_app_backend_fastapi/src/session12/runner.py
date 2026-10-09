"""plan_week の本体（worker の中で動く）。何度実行しても、進捗も結果も重複しないように書く。

- run_plan()：1回分の実行。開始 → 1日ずつ（中止フラグを見る → 記録済みなら飛ばす → 作って記録）→ 終了
- decide()  ：失敗をどう扱うか（一時的なら待って再試行、それ以外はすぐ failed）
- execute() ：Celery のタスクから呼ぶ入口。Redis の接続を作って閉じ、失敗を decide() に回す
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

from .errors import MESSAGES
from .planner import find_user, plan_day
from .store import NOT_RUNNING, JobStore

logger = logging.getLogger("kondate.session12.runner")

MAX_RETRIES = 3  # 再試行の上限（最初の1回を含めて最大4回実行する）
BACKOFF_BASE = 2.0  # 1回目の再試行の待ち（秒）の上限。2倍ずつ増やす
BACKOFF_CAP = 60.0

Sleep = Callable[[float], Awaitable[None]]
DayPlanner = Callable[[dict, int, date], dict]


class TransientJobError(Exception):
    """時間をおけば成功しうる失敗（上流の 5xx・タイムアウトなど）。"""


# 再試行してよい失敗。これ以外（UnknownUser・ValueError・想定外の例外）は、やり直しても同じ結果になる
TRANSIENT: tuple[type[BaseException], ...] = (TransientJobError, RedisConnectionError, RedisTimeoutError, TimeoutError)


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    countdown: float | None = None  # 再試行までの待ち（秒）


def decide(exc: BaseException, retries: int, *, rand: Callable[[], float] = random.random) -> RetryDecision:
    """retries はこれまでに再試行した回数（Celery の self.request.retries）。"""
    if isinstance(exc, TRANSIENT) and retries < MAX_RETRIES:
        ceiling = min(BACKOFF_CAP, BACKOFF_BASE * 2 ** retries)
        return RetryDecision(True, ceiling * (0.5 + rand() / 2))  # 半分は必ず待ち、残り半分をばらつかせる
    return RetryDecision(False)


async def run_plan(store: JobStore, job_id: str, *, sleep: Sleep = asyncio.sleep,
                   day_planner: DayPlanner = plan_day) -> str | None:
    """1回分の実行。終わったときの状態を返す（ジョブが無ければ None）。"""
    job = await store.get(job_id)
    if job is None:
        return None  # 保存期限が過ぎた・登録に失敗して消した。再配送されても何もしない
    status = await store.start(job_id)
    if status != "running":
        return status  # キャンセル済み・終了済み（再配送）なら何もしない
    user = find_user(job.user_id)  # 見つからなければ UnknownUser（恒久的な失敗）
    start = date.fromisoformat(job.start_date)
    recorded = await store.recorded_days(job_id)
    for i in range(job.total):
        if await store.cancel_requested(job_id):  # 日の区切りごとに中止フラグを見る
            return await store.finish(job_id, "cancelled", "", job.result_ttl)
        if i in recorded:
            continue  # 前の実行が記録した日はやり直さない
        await sleep(job.work_seconds)  # 1日分の重い処理（LLM の呼び出しなど）の代役
        if await store.advance(job_id, i, day_planner(user, i, start)) == NOT_RUNNING:
            return await store.status(job_id)
    days = await store.recorded_days(job_id)
    result = {"days": [days[i] for i in range(job.total)]}  # 結果は記録から組み立てる（進捗と食い違わない）
    return await store.finish(job_id, "succeeded", json.dumps(result, ensure_ascii=False), job.result_ttl)


async def execute(job_id: str, *, retries: int, sleep: Sleep = asyncio.sleep, day_planner: DayPlanner = plan_day,
                  rand: Callable[[], float] = random.random) -> float | None:
    """worker の1回の実行。再試行するなら待ち秒数を、終わったなら None を返す。"""
    redis = make_redis()
    store = JobStore(redis)
    try:
        try:
            await run_plan(store, job_id, sleep=sleep, day_planner=day_planner)
            return None
        except Exception as exc:
            decision = decide(exc, retries, rand=rand)
            if decision.retry:
                logger.warning("plan_week_retry job_id=%s retries=%d countdown=%.1f error=%s",
                               job_id, retries, decision.countdown, type(exc).__name__)
                return decision.countdown
            logger.error("plan_week_failed job_id=%s retries=%d error=%s", job_id, retries,
                         type(exc).__name__, exc_info=exc)
            job = await store.get(job_id)
            if job is not None:
                # クライアントに見せるのは固定文と、ジョブを登録したリクエストの ID だけ（例外の文は出さない）
                error = {"type": "internal_error", "message": MESSAGES["internal_error"], "request_id": job.request_id}
                await store.finish(job_id, "failed", json.dumps(error, ensure_ascii=False), job.result_ttl)
            return None
    finally:
        await redis.aclose()
