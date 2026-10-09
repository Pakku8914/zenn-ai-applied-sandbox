"""サーバ側のツール呼び出しループ。mid01/loop.py のコピーに、次の1点だけ変更を入れたもの。

変更：StepDone を「ツールの結果を出し終えたあと」に出す（mid01 は結果より前に出していた）。
UI Message Stream では、サーバで実行したツールの tool-output-available を、同じステップの finish-step
より前に送る決まり（AI SDK の UI Message Stream Protocol）。StepDone をそのまま finish-step にできるよう、順序をループの側でそろえる。

prime_loop()・PrimedLoop は mid01/relay.py から移した（先読みはループ単位で行う）。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, replace

import anyio
from pydantic import ValidationError

from .providers import (ChatRequest, Done, LLMProvider, ProviderError, TextDelta, ToolCall, ToolCallDelta,
                        ToolCallDone, ToolCallStart, Usage)
from .tools import TOOLS, Tool, ToolContext, ToolError, tool_definitions

logger = logging.getLogger("kondate.final.loop")

TOOL_FAILED = "ツールの実行中にエラーが発生しました。別の方法を試すか、ユーザーに伝えてください。"
STEP_LIMIT = "ステップの上限に達したため、このツールは実行しませんでした。"


@dataclass(frozen=True)
class ToolLimits:
    max_steps: int = 5
    tool_timeout_s: float = 3.0
    max_output_chars: int = 4000


@dataclass(frozen=True)
class ToolResult:
    id: str
    name: str
    output: dict | str  # 成功は dict、失敗は LLM に読ませる日本語の文
    is_error: bool


@dataclass(frozen=True)
class StepDone:
    step: int
    stop_reason: str
    usage: Usage


@dataclass(frozen=True)
class LoopDone:
    stop_reason: str  # end_turn / max_tokens / max_steps（ほかに refusal など上流の値）
    usage: Usage
    steps: int
    messages: list[dict]


LoopEvent = TextDelta | ToolCallStart | ToolCallDelta | ToolCallDone | ToolResult | StepDone | LoopDone


async def close_upstream(upstream: AsyncIterator[object]) -> None:
    aclose = getattr(upstream, "aclose", None)
    if aclose is not None:
        with anyio.CancelScope(shield=True):
            await aclose()


def add_usage(a: Usage, b: Usage) -> Usage:
    return Usage(a.input_tokens + b.input_tokens, a.output_tokens + b.output_tokens,
                 a.cache_read_input_tokens + b.cache_read_input_tokens,
                 a.cache_creation_input_tokens + b.cache_creation_input_tokens)


def invalid_input_message(e: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in err['loc']) or '(全体)'}: {err['msg']}" for err in e.errors()[:5]]
    return "引数が正しくありません。" + " / ".join(parts)


def _error(call: ToolCall, message: str) -> ToolResult:
    return ToolResult(call.id, call.name, message, True)


async def execute_tool(call: ToolCall, ctx: ToolContext, *, tools: Mapping[str, Tool] = TOOLS,
                       limits: ToolLimits = ToolLimits()) -> ToolResult:
    tool = tools.get(call.name)
    if tool is None:
        return _error(call, f"{call.name} というツールはありません。")
    try:
        args = tool.input_model.model_validate(call.input)
    except ValidationError as e:
        return _error(call, invalid_input_message(e))
    timeout = tool.timeout_s or limits.tool_timeout_s
    try:
        async with asyncio.timeout(timeout):
            output = tool.run(args, ctx)
            if inspect.isawaitable(output):
                output = await output
        text = json.dumps(output, ensure_ascii=False)
    except ToolError as e:
        return _error(call, str(e))
    except TimeoutError:
        return _error(call, f"{call.name} が {timeout:g} 秒以内に終わりませんでした。")
    except Exception:
        logger.exception("tool_failed", extra={"tool": call.name, "tool_call_id": call.id})
        return _error(call, TOOL_FAILED)
    if len(text) > limits.max_output_chars:
        return _error(call, f"{call.name} の結果が大きすぎます（{len(text)} 文字・上限 {limits.max_output_chars} 文字）。"
                            "条件を絞って呼び直してください。")
    return ToolResult(call.id, call.name, output, False)


def tool_result_block(result: ToolResult) -> dict:
    content = result.output if isinstance(result.output, str) else json.dumps(result.output, ensure_ascii=False)
    return {"type": "tool_result", "tool_use_id": result.id, "content": content, "is_error": result.is_error}


def assistant_blocks(texts: list[str], calls: list[ToolCall]) -> list[dict]:
    text = "".join(texts)
    blocks: list[dict] = [{"type": "text", "text": text}] if text else []
    return blocks + [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in calls]


async def run_tool_loop(provider: LLMProvider, chat: ChatRequest, ctx: ToolContext, *,
                        tools: Mapping[str, Tool] = TOOLS,
                        limits: ToolLimits = ToolLimits()) -> AsyncIterator[LoopEvent]:
    messages = list(chat.messages)
    added: list[dict] = []
    total = Usage(0, 0)
    definitions = tool_definitions(tools)
    for step in range(1, limits.max_steps + 1):
        texts: list[str] = []
        calls: list[ToolCall] = []
        done: Done | None = None
        request = replace(chat, messages=list(messages), tools=definitions)
        upstream = provider.stream(request)
        try:
            async for ev in upstream:
                if isinstance(ev, Done):
                    done = ev
                    continue
                if isinstance(ev, TextDelta):
                    texts.append(ev.text)
                elif isinstance(ev, ToolCallDone):
                    calls.append(ToolCall(ev.id, ev.name, ev.input))
                yield ev
        finally:
            await close_upstream(upstream)
        assert done is not None
        total = add_usage(total, done.usage)
        assistant = {"role": "assistant", "content": assistant_blocks(texts, calls)}
        if done.stop_reason != "tool_use" or not calls:
            added.append(assistant)
            yield StepDone(step, done.stop_reason, done.usage)
            yield LoopDone(done.stop_reason, total, step, added)
            return
        results: list[ToolResult] = []
        for call in calls:
            if step == limits.max_steps:
                result = _error(call, STEP_LIMIT)
            else:
                result = await execute_tool(call, ctx, tools=tools, limits=limits)
            results.append(result)
            yield result
        yield StepDone(step, done.stop_reason, done.usage)  # 変更点：結果を出し終えてからステップを閉じる
        user = {"role": "user", "content": [tool_result_block(r) for r in results]}
        messages += [assistant, user]
        added += [assistant, user]
    yield LoopDone("max_steps", total, limits.max_steps, added)


# ---------------------------------------------------------------- 先読み（mid01/relay.py から）


@dataclass
class PrimedLoop:
    """最初のイベントまで読んだツールループ。chat は実際に送った要求（フォールバックならモデルが違う）。"""

    events: AsyncIterator[LoopEvent]
    first: LoopEvent
    chat: ChatRequest


async def prime_loop(provider: LLMProvider, chat: ChatRequest, ctx: ToolContext, *,
                     limits: ToolLimits = ToolLimits()) -> PrimedLoop:
    """1回目の LLM 呼び出しの最初のイベントまで読む。開始前の 429・529・接続失敗は ProviderError で上がる。"""
    events = run_tool_loop(provider, chat, ctx, limits=limits)
    try:
        first = await anext(events)
    except StopAsyncIteration:
        raise ProviderError("bad_response", provider=provider.name) from None
    return PrimedLoop(events, first, chat)


async def with_first(first: LoopEvent, rest: AsyncIterator[LoopEvent]) -> AsyncIterator[LoopEvent]:
    yield first
    async for ev in rest:
        yield ev
