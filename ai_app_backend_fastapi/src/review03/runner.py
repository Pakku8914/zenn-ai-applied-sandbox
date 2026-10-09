"""問題5：1日ずつ、予約してから LLM を呼ぶ plan_week の本体（worker の中で動く）。

session12/runner.py との違い：
- 1日分の「重い処理」の代役（sleep）を、metered_complete（待ち時間 → 予約 → リトライ・フォールバック → 精算）に置き換えた
- 失敗の分類に、上流の失敗（ProviderError）とクォータ切れ（QuotaExceeded）を足した
- 失敗の本文の種別を、API と同じ表（KIND_TO_ERROR）から引く
- execute_once は Redis・LLM・時計を引数で受け取る（検証で差し替えるため。Celery の再試行は呼び出し側が行う）
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from kondate.clock import Clock

from .errors import FALLBACK_ERROR, KIND_TO_ERROR, MESSAGES
from .fallback import FALLBACK_KINDS, ResilientLLM
from .limiter import Limiter
from .metered import QuotaExceeded, metered_complete
from .planner import find_user, plan_day
from .plans import LimitSettings
from .providers import ChatRequest, ProviderError
from .store import NOT_RUNNING, JobStore

logger = logging.getLogger("kondate.review03.runner")

MAX_RETRIES = 3  # ジョブ全体の再試行の上限（最初の1回を含めて最大4回実行する）
BACKOFF_BASE = 2.0
BACKOFF_CAP = 60.0  # 可視性タイムアウト（3600 秒）より十分短く
NOTE_MAX_TOKENS = 300  # 1日分のひとことの上限。予約は「入力の見積もり＋この値」

TRANSIENT: tuple[type[BaseException], ...] = (RedisConnectionError, RedisTimeoutError, TimeoutError)
# 上流の失敗のうち、時間をおけば通りうるもの（ResilientLLM が次の経路へ移る種類と同じ）
TRANSIENT_KINDS = FALLBACK_KINDS

DayPlanner = Callable[[dict, int, date], dict]


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    countdown: float | None = None  # 再試行までの待ち（秒）


def day_chat(day: dict) -> ChatRequest:
    """1日分の献立に、LLM でひとことを添えてもらう要求。"""
    ids = "・".join(day["recipe_ids"])
    text = f"{day['date']} の献立（{ids}）に、ひとことコメントを付けてください。"
    return ChatRequest(messages=[{"role": "user", "content": text}], max_tokens=NOTE_MAX_TOKENS)


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, ProviderError):
        return exc.kind in TRANSIENT_KINDS
    return isinstance(exc, TRANSIENT)


def decide(exc: BaseException, retries: int, *, rand: Callable[[], float] = random.random) -> RetryDecision:
    """retries はこれまでに再試行した回数（Celery の self.request.retries）。"""
    if not is_transient(exc) or retries >= MAX_RETRIES:
        return RetryDecision(False)
    ceiling = min(BACKOFF_CAP, BACKOFF_BASE * 2 ** retries)
    delay = ceiling * (0.5 + rand() / 2)
    if isinstance(exc, ProviderError) and exc.retry_after is not None:
        delay = max(delay, min(float(exc.retry_after), BACKOFF_CAP))  # 上流が示した時間より早くやり直さない
    return RetryDecision(True, delay)


def job_error(exc: BaseException, request_id: str) -> dict:
    """ジョブの失敗の本文。種別は API と同じ表から引き、文は固定文だけにする。"""
    if isinstance(exc, QuotaExceeded):
        type_ = "quota_exceeded"
    elif isinstance(exc, ProviderError):
        type_ = KIND_TO_ERROR.get(exc.kind, FALLBACK_ERROR)[1]
    else:
        type_ = "internal_error"
    return {"type": type_, "message": MESSAGES[type_], "request_id": request_id}


async def run_plan(store: JobStore, job_id: str, *, llm: ResilientLLM, limiter: Limiter,
                   limit_settings: LimitSettings, clock: Clock, day_planner: DayPlanner = plan_day) -> str | None:
    """1回分の実行。終わったときの状態を返す（ジョブが無ければ None）。"""
    job = await store.get(job_id)
    if job is None:
        return None
    status = await store.start(job_id)
    if status != "running":
        return status  # キャンセル済み・終了済み（再配送）なら何もしない
    user = find_user(job.user_id)
    limits = limit_settings.for_plan(user["plan"])  # 引くのはジョブの持ち主のプランのクォータ
    start = date.fromisoformat(job.start_date)
    recorded = await store.recorded_days(job_id)
    for i in range(job.total):
        if await store.cancel_requested(job_id):
            return await store.finish(job_id, "cancelled", "", job.result_ttl)
        if i in recorded:
            continue  # 前の実行が記録した日は、予約も LLM の呼び出しもしない
        day = day_planner(user, i, start)
        metered = await metered_complete(llm, limiter, job.user_id, limits, day_chat(day), clock=clock,
                                         hold_seconds=limit_settings.hold_seconds)
        record = {**day, "note": metered.served.value.text, "fallback": metered.served.fallback}
        if await store.advance(job_id, i, record) == NOT_RUNNING:
            return await store.status(job_id)
    days = await store.recorded_days(job_id)
    result = {"days": [days[i] for i in range(job.total)]}  # 結果は記録から組み立てる（進捗と食い違わない）
    return await store.finish(job_id, "succeeded", json.dumps(result, ensure_ascii=False), job.result_ttl)


async def execute_once(store: JobStore, job_id: str, *, retries: int, llm: ResilientLLM, limiter: Limiter,
                       limit_settings: LimitSettings, clock: Clock, rand: Callable[[], float] = random.random,
                       day_planner: DayPlanner = plan_day) -> float | None:
    """worker の1回の実行。再試行するなら待ち秒数を、終わったなら None を返す。"""
    try:
        await run_plan(store, job_id, llm=llm, limiter=limiter, limit_settings=limit_settings, clock=clock,
                       day_planner=day_planner)
        return None
    except Exception as exc:
        decision = decide(exc, retries, rand=rand)
        if decision.retry:
            logger.warning("plan_week_retry job_id=%s retries=%d countdown=%.1f error=%s",
                           job_id, retries, decision.countdown, type(exc).__name__)
            return decision.countdown
        logger.error("plan_week_failed job_id=%s retries=%d error=%s", job_id, retries, type(exc).__name__)
        job = await store.get(job_id)
        if job is not None:
            body = json.dumps(job_error(exc, job.request_id), ensure_ascii=False)
            await store.finish(job_id, "failed", body, job.result_ttl)
        return None
