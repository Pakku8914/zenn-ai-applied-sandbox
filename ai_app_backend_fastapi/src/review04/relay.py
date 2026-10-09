"""LLM の差分を自前の SSE（API契約③）で中継する。

session13 の relay（途中で終わったら usage を見積もる）と、session16 の relay（Drain の締め切りを守る）を1つにしたもの。

- prime()：上流の最初のイベントまで読む（セッション6）。ResilientLLM.prime() が、ここまでを再試行する（セッション11）
- relay()：上流を pump で読んでキューに入れ、「次の知らせ」と「Drain の締め切り」の早いほうを待つ（セッション16）
- どう終わっても finally で結末を決める。Done が届かなければ、送った分から usage を見積もる（セッション6・13）
台帳への記録はここではしない。metering.metered() が外側から包む（問題4）。
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass

import anyio
from fastapi.sse import ServerSentEvent

from .errors import stream_error_type
from .lifecycle import Drain
from .providers import ChatRequest, Done, LLMProvider, ProviderError, StreamEvent, TextDelta, Usage
from .sse import delta_event, done_event, error_event, start_event, usage_event

logger = logging.getLogger("kondate.review04.relay")

QUEUE_SIZE = 16
Item = tuple[str, object]  # ("event", StreamEvent) / ("error", 例外) / ("end", None)


def chat_for(message: str, max_tokens: int = 1024) -> ChatRequest:
    """利用者の発言1つから作る要求。アプリと録画で同じ関数を使い、要求の指紋をそろえる（問題5・7）。"""
    return ChatRequest(messages=[{"role": "user", "content": message}], max_tokens=max_tokens)


def estimate_tokens(text: str) -> int:
    """mockllm と同じ近似式 ceil(UTF-8 バイト数 / 3)。"""
    return math.ceil(len(text.encode("utf-8")) / 3)


def estimate_input_tokens(chat: ChatRequest) -> int:
    system = estimate_tokens(chat.system) if chat.system else 0
    return 4 + system + sum(3 + estimate_tokens(m["content"]) for m in chat.messages
                            if isinstance(m["content"], str))


@dataclass
class StreamOutcome:
    """1回のストリーミングの結末。ログ・課金計測に使う（クライアントには送らない）。"""

    request_id: str
    message_id: str
    input_estimate: int = 0
    reason: str | None = None  # completed / failed / drained / cancelled
    error_type: str | None = None
    deltas: int = 0
    output_bytes: int = 0
    stop_reason: str | None = None
    usage: Usage | None = None
    usage_source: str | None = None  # upstream（Done の値）/ estimated（見積もり）
    upstream_closed: bool = False


@dataclass
class Primed:
    chat: ChatRequest  # 実際に上流へ送った要求（フォールバックした経路のモデルが入っている）
    upstream: AsyncIterator[StreamEvent]
    first: StreamEvent | None
    started: float


async def prime(provider: LLMProvider, chat: ChatRequest) -> Primed:
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
    aclose = getattr(upstream, "aclose", None)
    if aclose is not None:
        with anyio.CancelScope(shield=True):
            await aclose()


async def pump(source: AsyncIterator[StreamEvent], queue: asyncio.Queue[Item]) -> None:
    """上流を読み、知らせをキューへ入れる。上流の失敗も ("error", 例外) という1件の知らせにする。"""
    try:
        async with aclosing(source):
            async for ev in source:
                await queue.put(("event", ev))
        await queue.put(("end", None))  # Done の無いまま上流が終わった
    except Exception as exc:  # CancelledError（止められた）は BaseException なので、ここには来ない
        await queue.put(("error", exc))


async def next_item(queue: asyncio.Queue[Item], drain: Drain) -> Item | None:
    """次の知らせと Drain の締め切りの、早いほうを待つ。締め切りなら None。"""
    if drain.expired.is_set():
        return None
    get = asyncio.ensure_future(queue.get())
    expired = asyncio.ensure_future(drain.expired.wait())
    try:
        await asyncio.wait((get, expired), return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (get, expired):
            if not task.done():
                task.cancel()
    if get.done() and not get.cancelled():
        return get.result()
    return None


async def relay(primed: Primed, *, outcome: StreamOutcome, drain: Drain) -> AsyncIterator[ServerSentEvent]:
    queue: asyncio.Queue[Item] = asyncio.Queue(maxsize=QUEUE_SIZE)
    producer = asyncio.create_task(pump(with_first(primed.first, primed.upstream), queue))
    try:
        yield start_event(outcome.message_id)
        while True:
            item = await next_item(queue, drain)
            if item is None:  # 締め切り：上流はまだ続いているが、ここで閉じる
                outcome.reason, outcome.error_type = "drained", "service_unavailable"
                yield error_event("service_unavailable", outcome.request_id)
                break
            kind, value = item
            if kind == "event":
                if isinstance(value, TextDelta):
                    outcome.deltas += 1
                    outcome.output_bytes += len(value.text.encode("utf-8"))
                    yield delta_event(value.text)
                elif isinstance(value, Done):
                    outcome.reason, outcome.stop_reason = "completed", value.stop_reason
                    outcome.usage, outcome.usage_source = value.usage, "upstream"
                    yield usage_event(value.usage.input_tokens, value.usage.output_tokens)
                    yield done_event(value.stop_reason)
                    break
                continue  # ツール呼び出しの差分は、この復習では中継しない
            exc = value if isinstance(value, BaseException) else ProviderError("bad_response", provider="relay")
            outcome.reason, outcome.error_type = "failed", stream_error_type(exc)
            logger.warning("stream_failed", extra={"request_id": outcome.request_id, "error_type": outcome.error_type,
                                                   "exc_type": type(exc).__name__})
            yield error_event(outcome.error_type, outcome.request_id)
            break
    finally:
        producer.cancel()  # まだ読んでいれば止める。pump の aclosing が上流のストリームを閉じる
        with anyio.CancelScope(shield=True):
            await asyncio.gather(producer, return_exceptions=True)
            await close_upstream(primed.upstream)
        outcome.upstream_closed = True
        outcome.reason = outcome.reason or "cancelled"
        if outcome.usage is None:  # Done が届かなかった：送った分から見積もる
            outcome.usage = Usage(outcome.input_estimate, math.ceil(outcome.output_bytes / 3))
            outcome.usage_source = "estimated"
        # request_id は文脈（contextvars）にもあるが、文脈の無い所（直接回すテスト）でも行に残るよう extra にも渡す
        logger.info("stream_closed", extra={
            "request_id": outcome.request_id, "reason": outcome.reason, "error_type": outcome.error_type,
            "deltas": outcome.deltas, "usage_source": outcome.usage_source,
            "input_tokens": outcome.usage.input_tokens, "output_tokens": outcome.usage.output_tokens})
