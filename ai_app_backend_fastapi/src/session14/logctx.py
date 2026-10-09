"""ログに自動で載せる「いまの文脈」。リクエストやジョブごとに別の値を持てる contextvars で持つ。

グローバル変数だと、同時に処理している別のリクエストの値で上書きされる。
ContextVar は asyncio のタスクごとに値が分かれ、そこから作ったタスクや asyncio.to_thread のスレッドへ引き継がれる。
"""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)


def current_request_id() -> str | None:
    return request_id_var.get()
