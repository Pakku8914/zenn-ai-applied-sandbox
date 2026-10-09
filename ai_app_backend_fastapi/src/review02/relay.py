"""ツール呼び出しループを先読みし、自前の SSE（API契約③）で中継して、終わったら保存する。

- prime_loop()（問題5）：セッション6の prime() をループに当てはめたもの。1回目の LLM 呼び出しの最初のイベントまで読む
- relay_turn()（問題6）：セッション8の relay_tool_loop() に、保存（セッション7）と StepDone の usage の集計を足したもの
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.sse import ServerSentEvent

from .errors import stream_error_type
from .loop import LoopDone, LoopEvent, StepDone, ToolLimits, ToolResult, add_usage, close_upstream, run_tool_loop
from .providers import (ChatRequest, LLMProvider, ProviderError, TextDelta, ToolCallDelta, ToolCallDone,
                        ToolCallStart, Usage)
from .sse import delta_event, done_event, error_event, start_event, tool_call_event, tool_result_event, usage_event
from .tools import TOOLS, Tool, ToolContext

logger = logging.getLogger("kondate.review02.relay")

# ---------------------------------------------------------------- 問題5：ループの先読み


@dataclass
class PrimedLoop:
    """最初のイベントまで読んだループ。events は続きを読むためのジェネレータ。"""

    events: AsyncIterator[LoopEvent]
    first: LoopEvent


async def prime_loop(provider: LLMProvider, chat: ChatRequest, ctx: ToolContext, *,
                     tools: Mapping[str, Tool] = TOOLS, limits: ToolLimits = ToolLimits()) -> PrimedLoop:
    """1回目の LLM 呼び出しの最初のイベントまで読む。429・タイムアウトなどは、ここで ProviderError として上がる。"""
    events = run_tool_loop(provider, chat, ctx, tools=tools, limits=limits)  # まだ何も送っていない
    try:
        first = await anext(events)  # ここで初めて1回目の要求を送る
    except StopAsyncIteration:
        raise ProviderError("bad_response", provider=provider.name) from None  # 何も返さずに終わった
    return PrimedLoop(events, first)


async def with_first(first: LoopEvent, rest: AsyncIterator[LoopEvent]) -> AsyncIterator[LoopEvent]:
    """先読みした1件を先頭に戻す。"""
    yield first
    async for ev in rest:
        yield ev


# ---------------------------------------------------------------- 問題6：中継と保存


@dataclass
class TurnOutcome:
    """1往復の結末。ログと検証に使う（クライアントには送らない）。"""

    request_id: str
    message_id: str  # 保存する最後の assistant の ID（start で先に知らせる）
    reason: str | None = None  # completed / client_disconnected / failed / cancelled
    error_type: str | None = None  # failed のとき、error イベントで送った種別
    steps: int = 0  # 終わった LLM 呼び出しの数（届いた StepDone の数）
    step_in_progress: bool = False  # LLM の差分を受け取っている途中で終わったか
    usage: Usage = field(default_factory=lambda: Usage(0, 0))  # 届いた StepDone の usage の合計（上流の値）
    tools: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    saved: bool = False


Saver = Callable[[list[dict]], Awaitable[bool]]


async def relay_turn(request: Request, primed: PrimedLoop, outcome: TurnOutcome, save: Saver,
                     on_close: Callable[[TurnOutcome], None] | None = None) -> AsyncIterator[ServerSentEvent]:
    events = with_first(primed.first, primed.events)
    try:
        yield start_event(outcome.message_id)
        async for ev in events:
            if isinstance(ev, StepDone):
                # 届いた usage は、切断を確かめるより先に数える（上流が確定させた値なので捨てない）
                outcome.steps, outcome.step_in_progress = ev.step, False
                outcome.usage = add_usage(outcome.usage, ev.usage)
                continue
            if await request.is_disconnected():
                outcome.reason = "client_disconnected"
                break  # 読むのをやめる。ループ（と、その中の上流）は finally で閉じる
            if isinstance(ev, (TextDelta, ToolCallStart, ToolCallDelta, ToolCallDone)):
                outcome.step_in_progress = True
            if isinstance(ev, TextDelta):
                yield delta_event(ev.text)
            elif isinstance(ev, ToolCallDone):
                yield tool_call_event(ev.id, ev.name, ev.input)  # 引数がそろってから1回だけ送る
            elif isinstance(ev, ToolResult):
                outcome.tools.append(f"{ev.name}:{'error' if ev.is_error else 'ok'}")
                yield tool_result_event(ev.id, ev.output, ev.is_error)
            elif isinstance(ev, LoopDone):
                outcome.stop_reason = ev.stop_reason
                if not await save(ev.messages):  # 保存できてから usage と done を送る（セッション7）
                    outcome.reason, outcome.error_type = "failed", "internal_error"
                    yield error_event("internal_error", outcome.request_id)
                    return
                outcome.reason, outcome.saved = "completed", True
                yield usage_event(ev.usage)
                yield done_event(ev.stop_reason)
    except Exception as e:  # asyncio.CancelledError・GeneratorExit は BaseException なので、ここには来ない
        outcome.reason, outcome.error_type = "failed", stream_error_type(e)
        if isinstance(e, ProviderError):
            logger.warning("turn_failed request_id=%s provider=%s kind=%s upstream_request_id=%s",
                           outcome.request_id, e.provider, e.kind, e.request_id or "-")
        else:
            logger.exception("turn_failed request_id=%s 想定外の例外", outcome.request_id)
        yield error_event(outcome.error_type, outcome.request_id)  # 200 のまま、イベントで失敗を伝えて終える
    finally:
        await close_upstream(events)
        await close_upstream(primed.events)
        outcome.reason = outcome.reason or "cancelled"  # 送信中にフレームワークから止められた
        logger.info("turn_closed request_id=%s message_id=%s reason=%s steps=%d in_progress=%s tools=%s "
                    "input_tokens=%d output_tokens=%d saved=%s", outcome.request_id, outcome.message_id,
                    outcome.reason, outcome.steps, outcome.step_in_progress, ",".join(outcome.tools),
                    outcome.usage.input_tokens, outcome.usage.output_tokens, outcome.saved)
        if on_close is not None:
            on_close(outcome)
