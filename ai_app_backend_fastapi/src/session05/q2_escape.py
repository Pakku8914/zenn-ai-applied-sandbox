"""練習問題2の解答：ensure_ascii の違いをバイト数で比べ、raw_data で送るエンドポイントを作る。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent

from .sse import sse_event

PAYLOAD = {"text": "鶏むね肉とキャベツ"}


def data_bytes(payload: dict) -> dict[bool, int]:
    """ensure_ascii が False / True のときの JSON の UTF-8 バイト数。"""
    return {flag: len(json.dumps(payload, ensure_ascii=flag).encode("utf-8")) for flag in (False, True)}


app = FastAPI(title="練習問題2")


@app.get("/q2/delta", response_class=EventSourceResponse)
async def delta() -> AsyncIterator[ServerSentEvent]:
    yield sse_event("delta", PAYLOAD)
