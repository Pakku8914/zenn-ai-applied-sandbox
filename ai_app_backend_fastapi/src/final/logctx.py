"""ログに自動で載せる「いまの文脈」（session16/logctx.py のコピー）。"""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("final_request_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("final_job_id", default=None)
