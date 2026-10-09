"""リクエストID をジョブへ運ぶ（Celery のメッセージヘッダ＋シグナル）。

api 側    before_task_publish：いまの request_id を、メッセージのヘッダ kondate_request_id に足す
worker 側 task_prerun        ：ヘッダの request_id と task_id（＝job_id）を contextvars に入れる
          task_postrun       ：消す（同じ子プロセスで動く次のタスクに持ち越さない）
タスクの引数にも、ジョブの記録にも request_id を入れなくてよい。
"""

from __future__ import annotations

import sys

from celery.signals import before_task_publish, task_postrun, task_prerun, worker_process_init

from .jsonlog import setup_json_logging
from .logctx import job_id_var, request_id_var
from .middleware import REQUEST_ID_RE

CELERY_HEADER = "kondate_request_id"


def attach_request_id(headers: dict | None = None, **_: object) -> None:
    rid = request_id_var.get()
    if rid is not None and headers is not None:
        headers.setdefault(CELERY_HEADER, rid)  # retry で積み直すときは、最初のヘッダをそのまま残す


def _header(request: object, name: str) -> object:
    """worker が受け取ったメッセージなら task.request の属性に、apply() で直接動かすと task.request.headers に入る。"""
    value = getattr(request, name, None)
    if value is None:
        value = (getattr(request, "headers", None) or {}).get(name)
    return value


def bind_job_context(task_id: str | None = None, task: object | None = None, **_: object) -> None:
    rid = _header(task.request, CELERY_HEADER) if task is not None else None
    request_id_var.set(rid if isinstance(rid, str) and REQUEST_ID_RE.fullmatch(rid) else None)
    job_id_var.set(task_id)


def clear_job_context(**_: object) -> None:
    request_id_var.set(None)
    job_id_var.set(None)


def setup_worker_logging(**_: object) -> None:
    # Celery は worker の sys.stdout を自分のロガーへ付け替える（worker_redirect_stdouts）。
    # そこへ書くと JSON の前に Celery の書式が付くので、元の標準出力（sys.__stdout__）へ書く
    setup_json_logging("kondate.session14", stream=sys.__stdout__)


def install_celery_signals() -> None:
    """何度呼んでも、それぞれ1回だけつながる（dispatch_uid）。"""
    before_task_publish.connect(attach_request_id, weak=False, dispatch_uid="s14.attach_request_id")
    task_prerun.connect(bind_job_context, weak=False, dispatch_uid="s14.bind_job_context")
    task_postrun.connect(clear_job_context, weak=False, dispatch_uid="s14.clear_job_context")
    worker_process_init.connect(setup_worker_logging, weak=False, dispatch_uid="s14.worker_logging")
