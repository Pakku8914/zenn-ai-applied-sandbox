"""自前の SSE プロトコル（API契約③）のイベントを作る部品。session05 の sse.py に tool_call・tool_result・error を足したもの。

start {message_id} → delta {text}… → tool_call {id, name, input} → tool_result {id, output, is_error} →（繰り返し）
→ usage {input_tokens, output_tokens} → done {stop_reason}。失敗は error {type, message, request_id} で終える。
"""

from __future__ import annotations

import json

from fastapi.sse import ServerSentEvent

from .providers import Usage


def sse_event(name: str, payload: dict) -> ServerSentEvent:
    # data= に dict を渡すと日本語が \uXXXX になるので、1行の JSON を自分で作って raw_data で渡す
    return ServerSentEvent(event=name, raw_data=json.dumps(payload, ensure_ascii=False))


def start_event(message_id: str) -> ServerSentEvent:
    return sse_event("start", {"message_id": message_id})


def delta_event(text: str) -> ServerSentEvent:
    return sse_event("delta", {"text": text})


def tool_call_event(id_: str, name: str, input_: dict) -> ServerSentEvent:
    return sse_event("tool_call", {"id": id_, "name": name, "input": input_})


def tool_result_event(id_: str, output: dict | str, is_error: bool) -> ServerSentEvent:
    return sse_event("tool_result", {"id": id_, "output": output, "is_error": is_error})


def usage_event(usage: Usage) -> ServerSentEvent:
    return sse_event("usage", {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})


def done_event(stop_reason: str) -> ServerSentEvent:
    return sse_event("done", {"stop_reason": stop_reason})


def error_event(payload: dict) -> ServerSentEvent:
    return sse_event("error", payload)
