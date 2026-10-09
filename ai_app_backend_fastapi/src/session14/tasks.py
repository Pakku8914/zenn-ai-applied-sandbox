"""Session 14 の Celery タスク。worker が起動時に src/*/tasks.py を読み込む。

Celery は自動リロードしないので、このファイル（と import 先）を変えたら worker を再起動する：
    docker compose restart worker

request_id はタスクの引数に入れない。api 側の before_task_publish がメッセージのヘッダに入れ、
worker 側の task_prerun が contextvars に戻す（celery_context.py）。
"""

from __future__ import annotations

import asyncio

from kondate.worker import app

from .celery_context import install_celery_signals
from .runner import execute

install_celery_signals()


@app.task(name="s14.plan_week", ignore_result=True)
def plan_week(job_id: str) -> None:
    """引数は job_id だけ（session12 と同じ）。task_id にも同じ値を使うので、ログの job_id になる。"""
    asyncio.run(execute(job_id))
