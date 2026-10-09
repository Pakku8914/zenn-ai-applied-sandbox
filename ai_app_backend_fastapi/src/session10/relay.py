"""LLM の差分を自前の SSE（API契約③）で中継する（session06/relay.py のコピー）。

- prime()：上流の最初のイベントまで読む。ここで失敗すれば、まだ 200 を返していないので JSON で返せる
- relay_chat()：先読みした1件から中継を続ける。途中の失敗は error イベントで終える
- キャンセル・切断・失敗のときは、送った差分から usage を見積もって StreamOutcome に残す（精算に使う）
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import anyio
from fastapi import Request
from fastapi.sse import ServerSentEvent

from .errors import stream_error_type
from .providers import ChatRequest, Done, LLMProvider, ProviderError, StreamEvent, TextDelta, Usage
from .sse import delta_event, done_event, error_event, start_event, usage_event

logger = logging.getLogger("kondate.session10.relay")


def estimate_tokens(text: str) -> int:
    """mockllm と同じ近似式 ceil(UTF-8 バイト数 / 3)。本物のトークナイザとは一致しない（多めに出やすい）。"""
    return math.ceil(len(text.encode("utf-8")) / 3)


def estimate_input_tokens(chat: ChatRequest) -> int:
    """入力トークンの見積もり。文字列の content だけを数える。"""
    return 4 + sum(3 + estimate_tokens(m["content"]) for m in chat.messages if isinstance(m["content"], str))


@dataclass
class StreamOutcome:
    """1回のストリーミングの結末。ログと精算に使う（クライアントには送らない）。"""

    request_id: str
    message_id: str
    input_estimate: int = 0
    reason: str | None = None  # completed / client_disconnected / cancelled / failed
    error_type: str | None = None
    deltas: int = 0
    output_bytes: int = 0
    ttft_ms: int | None = None
    stop_reason: str | None = None
    usage: Usage | None = None
    usage_source: str | None = None  # upstream（Done の値）/ estimated（途中で終わったので見積もり）
    upstream_closed: bool = False


@dataclass
class Primed:
    """最初のイベントまで読んだ上流。"""

    chat: ChatRequest
    upstream: AsyncIterator[StreamEvent]
    first: StreamEvent | None
    started: float


async def prime(provider: LLMProvider, chat: ChatRequest) -> Primed:
    """上流の最初のイベントまで読む。429・529 や接続の失敗は、ここで ProviderError として上がる。"""
    started = time.perf_counter()
    upstream = provider.stream(chat)
    try:
        first = await anext(upstream)
    except StopAsyncIteration:
        raise ProviderError("bad_response", provider=provider.name) from None
    return Primed(chat, upstream, first, started)


async def with_first(first: StreamEvent | None, rest: AsyncIterator[StreamEvent]) -> AsyncIterator[StreamEvent]:
    if first is not None:
        yield first
    async for ev in rest:
        yield ev


async def close_upstream(upstream: AsyncIterator[object]) -> None:
    """上流のストリームを閉じる。キャンセルされている最中でも最後までやり切るよう、シールドして待つ。"""
    aclose = getattr(upstream, "aclose", None)
    if aclose is not None:
        with anyio.CancelScope(shield=True):
            await aclose()


async def relay_chat(request: Request, primed: Primed, outcome: StreamOutcome,
                     on_close: Callable[[StreamOutcome], None] | None = None) -> AsyncIterator[ServerSentEvent]:
    events = with_first(primed.first, primed.upstream)
    try:
        yield start_event(outcome.message_id)
        async for ev in events:
            if await request.is_disconnected():
                outcome.reason = "client_disconnected"
                break
            if isinstance(ev, TextDelta):
                if outcome.ttft_ms is None:
                    outcome.ttft_ms = round((time.perf_counter() - primed.started) * 1000)
                outcome.deltas += 1
                outcome.output_bytes += len(ev.text.encode("utf-8"))
                yield delta_event(ev.text)
            elif isinstance(ev, Done):
                outcome.reason, outcome.stop_reason = "completed", ev.stop_reason
                outcome.usage, outcome.usage_source = ev.usage, "upstream"
                yield usage_event(ev.usage)
                yield done_event(ev.stop_reason)
    except Exception as e:
        outcome.reason, outcome.error_type = "failed", stream_error_type(e)
        if isinstance(e, ProviderError):
            logger.warning("stream_failed request_id=%s provider=%s kind=%s upstream_request_id=%s",
                           outcome.request_id, e.provider, e.kind, e.request_id or "-")
        else:
            logger.exception("stream_failed request_id=%s 想定外の例外", outcome.request_id)
        yield error_event(outcome.error_type, outcome.request_id)
    finally:
        await close_upstream(events)
        await close_upstream(primed.upstream)
        outcome.upstream_closed = True
        outcome.reason = outcome.reason or "cancelled"
        if outcome.usage is None:  # Done が届かなかった：送った分から見積もる
            outcome.usage = Usage(outcome.input_estimate, math.ceil(outcome.output_bytes / 3))
            outcome.usage_source = "estimated"
        logger.info("stream_closed request_id=%s message_id=%s reason=%s error_type=%s deltas=%d "
                    "usage_source=%s input_tokens=%d output_tokens=%d", outcome.request_id, outcome.message_id,
                    outcome.reason, outcome.error_type, outcome.deltas, outcome.usage_source,
                    outcome.usage.input_tokens, outcome.usage.output_tokens)
        if on_close is not None:
            on_close(outcome)
