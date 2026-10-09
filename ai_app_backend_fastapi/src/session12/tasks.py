"""Session 12 の Celery タスク。worker が起動時に src/*/tasks.py を読み込む。

Celery は自動リロードしないので、このファイル（と import 先）を変えたら worker を再起動する：
    docker compose restart worker
"""

from __future__ import annotations

import asyncio

from kondate.worker import app

from .runner import MAX_RETRIES, execute


@app.task(name="s12.plan_week", bind=True, acks_late=True, reject_on_worker_lost=True,
          ignore_result=True, max_retries=MAX_RETRIES)
def plan_week(self, job_id: str) -> None:
    """1週間の献立づくり。引数は job_id だけで、条件は Redis のジョブ（s12:job:{job_id}）から読む。

    acks_late=True：終わってから ack する（途中で worker が落ちたら、メッセージは再配送される）
    reject_on_worker_lost=True：子プロセスが強制終了されたら、失敗扱いにせずキューへ戻す
    ignore_result=True：結果は自分で s12:job:{job_id} に保存するので、Celery の結果バックエンドには書かない
    """
    countdown = asyncio.run(execute(job_id, retries=self.request.retries))
    if countdown is not None:
        raise self.retry(countdown=countdown)  # 同じ task_id（＝job_id）のまま、新しいメッセージとして積み直す
