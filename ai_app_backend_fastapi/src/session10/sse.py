"""自前の SSE プロトコル（API契約③）のイベントを作る部品（session06/sse.py のコピー）。"""

from __future__ import annotations

import json

from fastapi.sse import ServerSentEvent

from .errors import MESSAGES
from .providers import Usage


def sse_event(name: str, payload: dict, *, event_id: str | None = None) -> ServerSentEvent:
    # data= に dict を渡すと日本語が \uXXXX になるので、1行の JSON にして raw_data で渡す
    return ServerSentEvent(event=name, raw_data=json.dumps(payload, ensure_ascii=False), id=event_id)


def start_event(message_id: str) -> ServerSentEvent:
    return sse_event("start", {"message_id": message_id})


def delta_event(text: str) -> ServerSentEvent:
    return sse_event("delta", {"text": text})


def usage_event(usage: Usage) -> ServerSentEvent:
    return sse_event("usage", {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})


def done_event(stop_reason: str) -> ServerSentEvent:
    return sse_event("done", {"stop_reason": stop_reason})


def error_event(type_: str, request_id: str) -> ServerSentEvent:
    """ストリームの途中の失敗。message は固定文、request_id はこちらが採番した req_+ULID。"""
    return sse_event("error", {"type": type_, "message": MESSAGES[type_], "request_id": request_id})
