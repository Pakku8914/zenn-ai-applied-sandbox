"""自前の SSE プロトコル（API契約③）のイベント（session16/sse.py のコピー）。"""

from __future__ import annotations

import json

from fastapi.sse import ServerSentEvent

from .errors import MESSAGES


def sse_event(name: str, payload: dict) -> ServerSentEvent:
    return ServerSentEvent(event=name, raw_data=json.dumps(payload, ensure_ascii=False))


def start_event(message_id: str) -> ServerSentEvent:
    return sse_event("start", {"message_id": message_id})


def delta_event(text: str) -> ServerSentEvent:
    return sse_event("delta", {"text": text})


def usage_event(input_tokens: int, output_tokens: int) -> ServerSentEvent:
    return sse_event("usage", {"input_tokens": input_tokens, "output_tokens": output_tokens})


def done_event(stop_reason: str | None) -> ServerSentEvent:
    return sse_event("done", {"stop_reason": stop_reason})


def error_event(type_: str, request_id: str) -> ServerSentEvent:
    return sse_event("error", {"type": type_, "message": MESSAGES[type_], "request_id": request_id})
