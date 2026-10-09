"""ツール付きの1往復を、先読み → 中継 → 保存 → usage/done の順で流す（このプロジェクトで書く部品）。

session06 の prime()／relay_chat()（開始前は JSON・開始後は error イベント）と、session08 の relay_tool_loop()
（tool_call・tool_result）と、session07 の「保存を確かめてから done」を1つにしたもの。

結末ごとの保存（turn.py の TurnRecorder が中身を決める）：
- completed … done まで届いた。completed() を保存してから usage → done（保存に失敗したら error internal_error）
- failed    … 上流の失敗・想定外の例外。interrupted() を保存してから error
- client_disconnected / cancelled … 送る先が無い。finally で interrupted() を保存する（シールドしてやり切る）
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

import anyio
from fastapi import Request
from fastapi.sse import ServerSentEvent

from .errors import stream_error_type
from .loop import LoopDone, LoopEvent, ToolLimits, ToolResult, close_upstream, run_tool_loop
from .providers import ChatRequest, LLMProvider, ProviderError, TextDelta, ToolCallDone, Usage
from .sse import (delta_event, done_event, error_event, start_event, tool_call_event, tool_result_event,
                  usage_event)
from .tools import ToolContext
from .turn import STEP_LIMIT_NOTE, StoredMessage, TurnRecorder

logger = logging.getLogger("kondate.mid01.relay")

SaveFn = Callable[[list[StoredMessage]], Awaitable[bool]]


@dataclass
class TurnOutcome:
    """1往復の結末。ログと検証に使う（クライアントには送らない）。"""

    request_id: str
    message_id: str
    reason: str | None = None  # completed / failed / client_disconnected / cancelled
    error_type: str | None = None  # failed のとき、error イベントで送った種別
    stop_reason: str | None = None  # LoopDone の値（end_turn / max_tokens / max_steps）
    saved: str | None = None  # complete / partial / failed（保存に失敗）
    tools: list[str] = field(default_factory=list)  # 実行（または拒否）したツールの名前と結果
    usage: Usage | None = None


@dataclass
class PrimedLoop:
    """最初のイベントまで読んだツールループ。"""

    events: AsyncIterator[LoopEvent]
    first: LoopEvent


async def prime_loop(provider: LLMProvider, chat: ChatRequest, ctx: ToolContext, *,
                     limits: ToolLimits = ToolLimits()) -> PrimedLoop:
    """1回目の LLM 呼び出しの最初のイベントまで読む。開始前の 429・529・接続失敗は ProviderError で上がる。"""
    events = run_tool_loop(provider, chat, ctx, limits=limits)
    try:
        first = await anext(events)
    except StopAsyncIteration:
        raise ProviderError("bad_response", provider=provider.name) from None
    return PrimedLoop(events, first)


async def with_first(first: LoopEvent, rest: AsyncIterator[LoopEvent]) -> AsyncIterator[LoopEvent]:
    """先読みした1件を先頭に戻す。"""
    yield first
    async for ev in rest:
        yield ev


async def relay_turn(request: Request, primed: PrimedLoop, recorder: TurnRecorder, outcome: TurnOutcome,
                     save: SaveFn, *, on_close: Callable[[TurnOutcome], None] | None = None,
                     ) -> AsyncIterator[ServerSentEvent]:
    events = with_first(primed.first, primed.events)
    attempted = False

    async def save_once(rows: list[StoredMessage], status: str) -> bool:
        nonlocal attempted
        attempted = True
        with anyio.CancelScope(shield=True):  # 切断で止められている最中でも、保存は最後までやり切る
            ok = await save(rows)
        outcome.saved = status if ok else "failed"
        return ok

    try:
        yield start_event(outcome.message_id)
        async for ev in events:
            if await request.is_disconnected():
                outcome.reason = "client_disconnected"
                break  # 読むのをやめる。ループ（と上流）は finally で閉じる
            recorder.feed(ev)
            if isinstance(ev, TextDelta):
                yield delta_event(ev.text)
            elif isinstance(ev, ToolCallDone):
                yield tool_call_event(ev.id, ev.name, ev.input)
            elif isinstance(ev, ToolResult):
                outcome.tools.append(f"{ev.name}:{'error' if ev.is_error else 'ok'}")
                yield tool_result_event(ev.id, ev.output, ev.is_error)
            elif isinstance(ev, LoopDone):
                outcome.stop_reason, outcome.usage = ev.stop_reason, ev.usage
                if ev.stop_reason == "max_steps":
                    yield delta_event(STEP_LIMIT_NOTE)  # 保存する締めの発言を、クライアントにも同じ文で見せる
                if not await save_once(recorder.completed(ev), "complete"):
                    outcome.reason, outcome.error_type = "failed", "internal_error"
                    yield error_event("internal_error", outcome.request_id)
                    return
                outcome.reason = "completed"
                # 保存できてから usage と done を送る（done を受け取った時点で、履歴に残っていることを保証する）
                yield usage_event(ev.usage)
                yield done_event(ev.stop_reason)
    except Exception as e:  # CancelledError・GeneratorExit は BaseException なので、ここには来ない
        outcome.reason, outcome.error_type = "failed", stream_error_type(e)
        if isinstance(e, ProviderError):
            logger.warning("turn_failed request_id=%s provider=%s kind=%s upstream_request_id=%s",
                           outcome.request_id, e.provider, e.kind, e.request_id or "-")
        else:
            logger.exception("turn_failed request_id=%s 想定外の例外", outcome.request_id)
        await save_once(recorder.interrupted(), "partial")  # 送ったところまでを残してから error を送る
        yield error_event(outcome.error_type, outcome.request_id)
    finally:
        await close_upstream(events)
        await close_upstream(primed.events)  # ループを閉じると、ループの中で上流も閉じられる
        outcome.reason = outcome.reason or "cancelled"
        if not attempted:  # 切断・キャンセル：送る先は無いが、送ったところまでは残す
            await save_once(recorder.interrupted(), "partial")
        logger.info("turn_closed request_id=%s message_id=%s reason=%s error_type=%s stop_reason=%s saved=%s "
                    "tools=%s", outcome.request_id, outcome.message_id, outcome.reason, outcome.error_type,
                    outcome.stop_reason, outcome.saved, ",".join(outcome.tools))
        if on_close is not None:
            on_close(outcome)
