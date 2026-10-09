"""最終プロジェクトの Celery タスク。worker が起動時に src/*/tasks.py を読み込む。

Celery は自動リロードしないので、このファイル（と import 先）を変えたら worker を再起動する：
    docker compose restart worker

ここで import してよいのは、worker でも軽く読める部品だけ（runner・store・planner・celery_context）。
app.py や chat.py を import しない（import エラーがあると、全セッションの worker が起動できなくなる）。
"""

from __future__ import annotations

import asyncio

from kondate.worker import app

from .celery_context import install_celery_signals
from .runner import MAX_RETRIES, execute

install_celery_signals()


@app.task(name="final.plan_week", bind=True, acks_late=True, reject_on_worker_lost=True,
          ignore_result=True, max_retries=MAX_RETRIES)
def plan_week(self, job_id: str) -> None:
    """1週間の献立づくり。引数は job_id だけで、条件は Redis のジョブ（final:job:{job_id}）から読む。"""
    countdown = asyncio.run(execute(job_id, retries=self.request.retries))
    if countdown is not None:
        raise self.retry(countdown=countdown)
