"""LLM の差分を自前の SSE（API契約③）で中継する。S06・S07・S08 はこのファイルをコピーして使う。

- 上流を待たずに start を送り、TextDelta を delta に、Done を usage → done にする
- クライアントの切断に気づいたら上流を読むのをやめ、finally で必ず上流を閉じる
- 結末（StreamOutcome）をログに残し、on_close に渡す
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import anyio
from fastapi import Request
from fastapi.sse import ServerSentEvent

from .providers import ChatRequest, Done, LLMProvider, TextDelta, Usage
from .sse import delta_event, done_event, start_event, usage_event

logger = logging.getLogger("kondate.session05.relay")


@dataclass
class StreamOutcome:
    """1回のストリーミングの結末。ログと検証に使う（クライアントには送らない）。"""

    request_id: str
    message_id: str
    reason: str | None = None  # completed / client_disconnected / cancelled / failed
    deltas: int = 0  # クライアントへ送った delta の数
    ttft_ms: int | None = None  # 受け付けてから最初の TextDelta が届くまで
    stop_reason: str | None = None
    usage: Usage | None = None
    upstream_closed: bool = False


async def close_upstream(upstream: AsyncIterator[object]) -> None:
    """上流のストリームを閉じる。キャンセルされている最中でも最後までやり切るよう、シールドして待つ。"""
    aclose = getattr(upstream, "aclose", None)
    if aclose is not None:
        with anyio.CancelScope(shield=True):
            await aclose()


async def relay_chat(request: Request, provider: LLMProvider, chat: ChatRequest, outcome: StreamOutcome,
                     on_close: Callable[[StreamOutcome], None] | None = None) -> AsyncIterator[ServerSentEvent]:
    started = time.perf_counter()
    upstream = provider.stream(chat)  # ここではまだ通信しない（最初に反復したときに始まる）
    try:
        yield start_event(outcome.message_id)  # 上流を待たずに送る。クライアントは「受け付けた」とすぐ分かる
        async for ev in upstream:
            if await request.is_disconnected():
                outcome.reason = "client_disconnected"
                break  # 読むのをやめる。上流は finally で閉じる
            if isinstance(ev, TextDelta):
                if outcome.ttft_ms is None:
                    outcome.ttft_ms = round((time.perf_counter() - started) * 1000)
                outcome.deltas += 1
                yield delta_event(ev.text)
            elif isinstance(ev, Done):
                outcome.reason, outcome.stop_reason, outcome.usage = "completed", ev.stop_reason, ev.usage
                yield usage_event(ev.usage)  # done の前に送る（done を受けたら閉じてよい、とクライアントに約束する）
                yield done_event(ev.stop_reason)
            # ToolCallStart などツールのイベントは、ツールのセッションで tool_call として送る。ここでは読み捨てる
    except Exception:
        outcome.reason = "failed"  # 途中の失敗を error イベントで伝えるのは異常系のセッションで扱う
        raise
    finally:
        await close_upstream(upstream)
        outcome.upstream_closed = True
        outcome.reason = outcome.reason or "cancelled"  # 送信中にフレームワークから止められた
        logger.info("stream_closed request_id=%s message_id=%s reason=%s deltas=%d ttft_ms=%s stop_reason=%s "
                    "output_tokens=%s", outcome.request_id, outcome.message_id, outcome.reason, outcome.deltas,
                    outcome.ttft_ms, outcome.stop_reason, outcome.usage.output_tokens if outcome.usage else None)
        if on_close is not None:
            on_close(outcome)
