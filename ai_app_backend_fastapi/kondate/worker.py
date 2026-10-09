"""Celery アプリ。各セッションのジョブは src/sessionNN/tasks.py に置けば自動で読み込まれる。

タスクを追加・変更したら worker を再起動する（Celery は自動リロードしない）：
    docker compose restart worker
"""

from __future__ import annotations

from pathlib import Path

from celery import Celery

from kondate.settings import get_settings

_settings = get_settings()
_root = Path(__file__).resolve().parent.parent
_session_tasks = sorted(f"src.{p.parent.name}.tasks" for p in (_root / "src").glob("*/tasks.py"))

app = Celery(
    "kondate",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
    include=_session_tasks,
)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Tokyo",
    broker_connection_retry_on_startup=True,
    result_expires=3600,
)


@app.task(name="kondate.ping")
def ping() -> str:
    return "pong"
