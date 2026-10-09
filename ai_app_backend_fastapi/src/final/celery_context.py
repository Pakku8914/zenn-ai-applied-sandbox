"""リクエストID をジョブへ運ぶ（session14/celery_context.py のコピー）。

api 側    before_task_publish：いまの request_id を、メッセージのヘッダ kondate_request_id に足す
worker 側 task_prerun        ：ヘッダの request_id と task_id（＝job_id）を contextvars に入れる
          task_postrun       ：消す
worker は src/*/tasks.py をすべて読むので、session14 のシグナルも同じプロセスにつながる。
dispatch_uid を final. で始めて、session14 の分と別の受け手として登録する（同じ uid だと片方が登録されない）。
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
        headers[CELERY_HEADER] = rid  # final の要求から積んだジョブは、final の request_id で上書きする


def _header(request: object, name: str) -> object:
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
    setup_json_logging("kondate.final", stream=sys.__stdout__)


def install_celery_signals() -> None:
    before_task_publish.connect(attach_request_id, weak=False, dispatch_uid="final.attach_request_id")
    task_prerun.connect(bind_job_context, weak=False, dispatch_uid="final.bind_job_context")
    task_postrun.connect(clear_job_context, weak=False, dispatch_uid="final.clear_job_context")
    worker_process_init.connect(setup_worker_logging, weak=False, dispatch_uid="final.worker_logging")
