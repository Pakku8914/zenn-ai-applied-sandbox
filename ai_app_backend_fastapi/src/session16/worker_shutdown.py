"""Celery worker の止め方（Session 12 の acks_late のジョブを、デプロイで取りこぼさずに止める）。

worker に届く信号と、そのときの動き：
- SIGTERM（docker stop の既定）… warm shutdown：新しいメッセージを取らず、実行中のタスクを終えてから止まる
- SIGQUIT                        … cold shutdown：実行中のタスクを待たずに止まる
- SIGKILL                        … 捕まえられない。docker は stop_grace_period（既定 10 秒）を過ぎるとこれを送る

acks_late=True のタスクは「終わってから ack」なので、途中で SIGKILL されても失われない。
ただし Redis のブローカーは、ack されないメッセージを visibility_timeout を過ぎてから再配送する（既定 3600 秒）。
"""

from __future__ import annotations

# 本番の worker に入れる設定（Session 12 の tasks.py はタスク単位で acks_late・reject_on_worker_lost を指定済み）
WORKER_SHUTDOWN_CONF: dict[str, object] = {
    "task_acks_late": True,  # 終わってから ack する（途中で落ちたら再配送）
    "task_reject_on_worker_lost": True,  # 子プロセスが強制終了されたら、失敗にせずキューへ戻す
    "worker_prefetch_multiplier": 1,  # 先取りは1件だけ（止めるときに抱えている未着手を減らす）
    "broker_transport_options": {"visibility_timeout": 3600},  # 最長タスクの2倍以上
}

# Celery 5.5 で入った soft shutdown（cold shutdown の前に、時間を区切って実行中のタスクを待つ）の設定名
SOFT_SHUTDOWN_SETTINGS = ("worker_soft_shutdown_timeout", "worker_enable_soft_shutdown_on_idle")

GRACE_TOO_SHORT = ("stop_grace_period が最長タスク以下：warm shutdown の途中で SIGKILL され、"
                   "visibility_timeout を過ぎるまで再配送されない")
VISIBILITY_TOO_SHORT = "visibility_timeout が最長タスクの2倍未満：実行中のタスクが別の worker にも配られうる"


def shutdown_problems(*, longest_task_seconds: float, stop_grace_seconds: float,
                      visibility_timeout_seconds: float) -> list[str]:
    """worker を止めるときの時間の関係を調べ、問題を文で返す（空なら問題なし）。"""
    problems: list[str] = []
    if stop_grace_seconds <= longest_task_seconds:
        problems.append(GRACE_TOO_SHORT)
    if visibility_timeout_seconds < 2 * longest_task_seconds:
        problems.append(VISIBILITY_TOO_SHORT)
    return problems
