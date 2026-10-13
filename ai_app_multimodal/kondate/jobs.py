"""プロセス内のジョブキュー（①バックエンド編のジョブキューの最小版）。

①は Celery＋Redis で別プロセスに逃がすが、本書の長い処理（大きな PDF の分割読み・まとめての文字起こし）は
api プロセスの中で asyncio のタスクとして動かす。プロセスが再起動するとジョブは消える（本番では①の構成にする）。

    queue = JobQueue(concurrency=1)
    job = queue.submit(work, total=10)      # work(progress) は async 関数。progress(done) で進捗を通知する
    async for ev in queue.events(job.id): ...  # {"status", "done", "total"} が届く
    queue.cancel(job.id)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ulid import ULID

Work = Callable[[Callable[[int], None]], Awaitable[Any]]
FINISHED = {"succeeded", "failed", "cancelled"}


@dataclass
class Job:
    id: str
    total: int
    status: str = "queued"          # queued / running / succeeded / failed / cancelled
    done: int = 0
    result: Any = None
    error: str | None = None
    _task: asyncio.Task | None = field(default=None, repr=False)
    _listeners: list[asyncio.Queue] = field(default_factory=list, repr=False)

    def snapshot(self) -> dict:
        return {"job_id": self.id, "status": self.status, "done": self.done, "total": self.total}


class JobQueue:
    def __init__(self, concurrency: int = 1) -> None:
        self._sem = asyncio.Semaphore(concurrency)
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _notify(self, job: Job) -> None:
        for q in job._listeners:
            q.put_nowait(job.snapshot())

    def submit(self, work: Work, total: int) -> Job:
        job = Job(id=f"job_{ULID()}", total=total)
        self._jobs[job.id] = job

        def progress(done: int) -> None:
            job.done = min(done, job.total)
            self._notify(job)

        async def run() -> None:
            try:
                async with self._sem:
                    job.status = "running"
                    self._notify(job)
                    job.result = await work(progress)
                    job.status = "succeeded"
            except asyncio.CancelledError:
                job.status = "cancelled"
            except Exception as e:  # 失敗の中身は種別だけ残す（生の例外文を利用者に返さない）
                job.status, job.error = "failed", type(e).__name__
            self._notify(job)

        job._task = asyncio.create_task(run())
        return job

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status in FINISHED or job._task is None:
            return False
        job._task.cancel()
        return True

    async def events(self, job_id: str) -> AsyncIterator[dict]:
        job = self._jobs[job_id]
        q: asyncio.Queue = asyncio.Queue()
        job._listeners.append(q)
        try:
            snap = job.snapshot()
            yield snap
            while snap["status"] not in FINISHED:
                snap = await q.get()
                yield snap
        finally:
            job._listeners.remove(q)
