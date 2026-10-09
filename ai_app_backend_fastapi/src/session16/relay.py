"""LLM の差分を自前の SSE（API契約③）で中継する。止め方（Drain）の締め切りを守れるように組み直したもの。

session06 の relay は「上流の次の差分」を直接待っていた。それだと上流が黙っている間は締め切りに気づけない。
ここでは上流を別のタスク（pump）で読んでキューに入れ、中継側は「次の知らせ」と「Drain の締め切り」の
早いほうを待つ。締め切りが先なら error（service_unavailable）を送って閉じ、pump を止めて上流も閉じる。

開始前の失敗を JSON で返す先読み（prime）は session06 のとおり。この章では省いている。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass

import anyio
from anthropic import AsyncAnthropic
from fastapi.sse import ServerSentEvent

from .config import ProdSettings
from .errors import stream_error_type
from .lifecycle import Drain, StreamGate
from .sse import delta_event, done_event, error_event, start_event, usage_event

logger = logging.getLogger("kondate.session16.relay")

Item = tuple[str, object]  # ("delta", 文字列) / ("done", {stop_reason, input_tokens, output_tokens}) / ("error", 例外)
QUEUE_SIZE = 16  # 中継が遅れたら pump も待つ（上流から読みすぎない）


@dataclass
class StreamOutcome:
    """1回のストリーミングの結末。ログと検証に使う（クライアントには送らない）。"""

    request_id: str
    message_id: str
    reason: str | None = None  # completed / failed / drained / rejected / cancelled
    error_type: str | None = None
    deltas: int = 0
    upstream_closed: bool = False


async def anthropic_events(client: AsyncAnthropic, settings: ProdSettings, message: str,
                           headers: dict[str, str]) -> AsyncIterator[Item]:
    """上流（Anthropic 互換）のストリームを、("delta", text) … ("done", {...}) の列にする。"""
    async with client.messages.stream(model=settings.llm_model, max_tokens=settings.llm_max_tokens,
                                      messages=[{"role": "user", "content": message}],
                                      extra_headers=headers or None) as stream:
        async for text in stream.text_stream:
            yield "delta", text
        final = await stream.get_final_message()
    yield "done", {"stop_reason": final.stop_reason, "input_tokens": final.usage.input_tokens,
                   "output_tokens": final.usage.output_tokens}


async def pump(source: AsyncIterator[Item], queue: asyncio.Queue[Item]) -> None:
    """上流を読み、知らせをキューへ入れる。上流の失敗も ("error", 例外) という1件の知らせにする。"""
    try:
        async with aclosing(source):
            async for item in source:
                await queue.put(item)
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


def _log_closed(outcome: StreamOutcome) -> None:
    logger.info("stream_closed", extra={"reason": outcome.reason, "error_type": outcome.error_type,
                                        "deltas": outcome.deltas, "upstream_closed": outcome.upstream_closed})


async def relay(source: AsyncIterator[Item], *, outcome: StreamOutcome, drain: Drain, gate: StreamGate,
                on_close: Callable[[StreamOutcome], None] | None = None) -> AsyncIterator[ServerSentEvent]:
    if not gate.try_enter():
        # 関所（admit_stream）を同時にすり抜けた分。もう 200 を返しているので、error イベントで断る
        outcome.reason, outcome.error_type = "rejected", "service_unavailable"
        _log_closed(outcome)
        if on_close is not None:
            on_close(outcome)
        yield error_event("service_unavailable", outcome.request_id)
        return

    queue: asyncio.Queue[Item] = asyncio.Queue(maxsize=QUEUE_SIZE)
    producer = asyncio.create_task(pump(source, queue))
    try:
        yield start_event(outcome.message_id)
        while True:
            item = await next_item(queue, drain)
            if item is None:  # 締め切り：上流はまだ続いているが、ここで閉じる
                outcome.reason, outcome.error_type = "drained", "service_unavailable"
                yield error_event("service_unavailable", outcome.request_id)
                break
            kind, value = item
            if kind == "delta":
                outcome.deltas += 1
                yield delta_event(str(value))
            elif kind == "done":
                assert isinstance(value, dict)
                outcome.reason = "completed"
                yield usage_event(value["input_tokens"], value["output_tokens"])
                yield done_event(value["stop_reason"])
                break
            else:
                assert isinstance(value, BaseException)
                outcome.reason, outcome.error_type = "failed", stream_error_type(value)
                logger.warning("stream_failed", extra={"error_type": outcome.error_type,
                                                       "exc_type": type(value).__name__})
                yield error_event(outcome.error_type, outcome.request_id)
                break
    finally:
        gate.leave()
        producer.cancel()  # まだ読んでいれば止める。pump の aclosing が上流のストリームを閉じる
        with anyio.CancelScope(shield=True):  # 切断で止められている最中でも、閉じ終わるまで待つ
            await asyncio.gather(producer, return_exceptions=True)
        outcome.upstream_closed = producer.done()
        outcome.reason = outcome.reason or "cancelled"
        _log_closed(outcome)
        if on_close is not None:
            on_close(outcome)
