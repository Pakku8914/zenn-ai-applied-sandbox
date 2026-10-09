"""ツール呼び出しループのイベントを、自前の SSE（API契約③）にして中継する。session05 の relay.py を手直ししたもの。

- 上流を待たずに start を送る。TextDelta → delta、ToolCallDone → tool_call、ToolResult → tool_result、
  LoopDone → usage（全ステップの合計）→ done
- ToolCallStart・ToolCallDelta・StepDone は、この SSE では送らない（UI Message Stream では使う）
- 上流の失敗（ProviderError）は error イベントで終える。クライアントの切断に気づいたらループを閉じる
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.sse import ServerSentEvent

from .errors import error_payload, error_type_of
from .loop import LoopDone, ToolLimits, ToolResult, close_upstream, run_tool_loop
from .providers import ChatRequest, LLMProvider, ProviderError, TextDelta, ToolCallDone, Usage
from .sse import delta_event, done_event, error_event, start_event, tool_call_event, tool_result_event, usage_event
from .tools import ToolContext

logger = logging.getLogger("kondate.session08.relay")


@dataclass
class LoopOutcome:
    """1回のストリーミングの結末。ログと検証に使う（クライアントには送らない）。"""

    request_id: str
    message_id: str
    reason: str | None = None  # completed / client_disconnected / failed / cancelled
    steps: int = 0
    tools: list[str] = field(default_factory=list)  # 実行（または拒否）したツールの名前と結果
    stop_reason: str | None = None
    usage: Usage | None = None
    messages: list[dict] = field(default_factory=list)  # 保存する発言（LoopDone.messages）


async def relay_tool_loop(request: Request, provider: LLMProvider, chat: ChatRequest, ctx: ToolContext,
                          outcome: LoopOutcome, *, limits: ToolLimits = ToolLimits(),
                          on_close: Callable[[LoopOutcome], None] | None = None) -> AsyncIterator[ServerSentEvent]:
    events = run_tool_loop(provider, chat, ctx, limits=limits)
    try:
        yield start_event(outcome.message_id)
        async for ev in events:
            if await request.is_disconnected():
                outcome.reason = "client_disconnected"
                break  # 読むのをやめる。実行中のループは finally で閉じる
            if isinstance(ev, TextDelta):
                yield delta_event(ev.text)
            elif isinstance(ev, ToolCallDone):
                yield tool_call_event(ev.id, ev.name, ev.input)  # 引数がそろってから1回だけ送る
            elif isinstance(ev, ToolResult):
                outcome.tools.append(f"{ev.name}:{'error' if ev.is_error else 'ok'}")
                yield tool_result_event(ev.id, ev.output, ev.is_error)
            elif isinstance(ev, LoopDone):
                outcome.reason, outcome.steps, outcome.stop_reason = "completed", ev.steps, ev.stop_reason
                outcome.usage, outcome.messages = ev.usage, ev.messages
                yield usage_event(ev.usage)
                yield done_event(ev.stop_reason)
    except ProviderError as e:
        outcome.reason = "failed"
        logger.warning("tool_loop_failed kind=%s upstream_request_id=%s request_id=%s",
                       e.kind, e.request_id, outcome.request_id)
        yield error_event(error_payload(error_type_of(e), outcome.request_id))
    finally:
        await close_upstream(events)  # ループを閉じると、ループの中で上流も閉じられる
        outcome.reason = outcome.reason or "cancelled"
        logger.info("tool_loop_closed request_id=%s reason=%s steps=%d tools=%s stop_reason=%s",
                    outcome.request_id, outcome.reason, outcome.steps, ",".join(outcome.tools), outcome.stop_reason)
        if on_close is not None:
            on_close(outcome)
