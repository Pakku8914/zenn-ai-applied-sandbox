"""練習問題5：worker を止めたとき、実行中のジョブがどうなるかを決める。"""

from __future__ import annotations


def stop_outcome(*, task_seconds: float, elapsed_at_stop: float, stop_grace_seconds: float,
                 visibility_timeout_seconds: int, acks_late: bool) -> str:
    """SIGTERM（warm shutdown）を受けたときに実行中だったタスクの行方。"""
    remaining = task_seconds - elapsed_at_stop
    if remaining <= stop_grace_seconds:
        return "最後まで実行して ack してから止まる"
    if acks_late:
        # 終わる前に SIGKILL：ack していないので Redis に残り、visibility_timeout の後に再配送される
        return f"SIGKILL で中断し、{visibility_timeout_seconds} 秒後に再配送される"
    return "SIGKILL で中断し、開始時に ack 済みなので失われる"
