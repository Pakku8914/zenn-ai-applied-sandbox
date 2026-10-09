"""練習問題4の解答：1日分の処理の途中でも中止フラグに気づき、その日を記録せずに止める。"""

from __future__ import annotations

import asyncio

from .planner import plan_day
from .runner import DayPlanner, run_plan
from .store import JobStore


class CancelledByUser(Exception):
    """1日分の処理の途中で中止フラグが立った。"""


async def cancellable_sleep(store: JobStore, job_id: str, seconds: float, *, poll: float = 0.1) -> bool:
    """seconds だけ待つ。途中で中止フラグが立ったら、すぐ True を返す。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while (left := deadline - loop.time()) > 0:
        if await store.cancel_requested(job_id):
            return True
        await asyncio.sleep(min(poll, left))
    return False  # 待ち終えた。この後のフラグは run_plan が次の日の区切りで見る


async def run_responsive(store: JobStore, job_id: str, *, poll: float = 0.1,
                         day_planner: DayPlanner = plan_day) -> str | None:
    async def sleep(seconds: float) -> None:
        if await cancellable_sleep(store, job_id, seconds, poll=poll):
            raise CancelledByUser  # advance() に進ませない＝途中の日を記録しない

    try:
        return await run_plan(store, job_id, sleep=sleep, day_planner=day_planner)
    except CancelledByUser:
        job = await store.get(job_id)
        if job is None:
            return None
        return await store.finish(job_id, "cancelled", "", job.result_ttl)
