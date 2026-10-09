"""サーバ側のツール呼び出しループ。LLM の差分を流しながら、tool_use をサーバで実行して結果を返す。

mid01・final はこのファイルを tools.py と一緒にコピーして使う（import しない）。
run_tool_loop() は SSE を知らない。出すのはループのイベントだけで、自前の SSE（API契約③）への変換は
relay.py、UI Message Stream への変換は最終プロジェクトが受け持つ。
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

from .providers import (ChatRequest, Done, LLMProvider, TextDelta, ToolCall, ToolCallDelta, ToolCallDone,
                        ToolCallStart, Usage)
from .tools import TOOLS, Tool, ToolContext, ToolError, tool_definitions

logger = logging.getLogger("kondate.session08.loop")

TOOL_FAILED = "ツールの実行中にエラーが発生しました。別の方法を試すか、ユーザーに伝えてください。"
STEP_LIMIT = "ステップの上限に達したため、このツールは実行しませんでした。"


@dataclass(frozen=True)
class ToolLimits:
    max_steps: int = 5  # LLM を呼ぶ回数の上限（1回目を含む）
    tool_timeout_s: float = 3.0  # ツール1回の制限時間（Tool.timeout_s があればそちら）
    max_output_chars: int = 4000  # tool_result に入れる JSON の文字数の上限


@dataclass(frozen=True)
class ToolResult:
    id: str
    name: str
    output: dict | str  # 成功は dict、失敗は LLM に読ませる日本語の文
    is_error: bool


@dataclass(frozen=True)
class StepDone:
    step: int  # 1 始まり
    stop_reason: str
    usage: Usage


@dataclass(frozen=True)
class LoopDone:
    stop_reason: str  # end_turn / max_tokens / max_steps
    usage: Usage  # 全ステップの合計
    steps: int
    messages: list[dict]  # このループで増えた発言（assistant と、tool_result だけの user）。保存に使う


LoopEvent = TextDelta | ToolCallStart | ToolCallDelta | ToolCallDone | ToolResult | StepDone | LoopDone


async def close_upstream(upstream: AsyncIterator[object]) -> None:
    """上流のストリームを閉じる（session05 の relay.py から）。キャンセル中でもやり切るようシールドする。"""
    aclose = getattr(upstream, "aclose", None)
    if aclose is not None:
        with anyio.CancelScope(shield=True):
            await aclose()


def add_usage(a: Usage, b: Usage) -> Usage:
    return Usage(a.input_tokens + b.input_tokens, a.output_tokens + b.output_tokens,
                 a.cache_read_input_tokens + b.cache_read_input_tokens,
                 a.cache_creation_input_tokens + b.cache_creation_input_tokens)


def invalid_input_message(e: ValidationError) -> str:
    """どの引数がなぜ駄目かだけを返す（受け取った値そのものは載せない）。"""
    parts = [f"{'.'.join(str(p) for p in err['loc']) or '(全体)'}: {err['msg']}" for err in e.errors()[:5]]
    return "引数が正しくありません。" + " / ".join(parts)


def _error(call: ToolCall, message: str) -> ToolResult:
    return ToolResult(call.id, call.name, message, True)


async def execute_tool(call: ToolCall, ctx: ToolContext, *, tools: Mapping[str, Tool] = TOOLS,
                       limits: ToolLimits = ToolLimits()) -> ToolResult:
    """ツールを1つ実行する。どんな失敗も is_error の結果にして返し、例外で呼び出し側を壊さない。"""
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
    except Exception:  # CancelledError は BaseException なのでここでは捕まえない（キャンセルは伝える）
        logger.exception("tool_failed name=%s id=%s", call.name, call.id)
        return _error(call, TOOL_FAILED)  # 例外の文は LLM にもクライアントにも見せない
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
    """LLM を呼ぶ → tool_use を実行 → 結果を足して呼び直す、を end_turn か上限まで繰り返す。

    ProviderError（上流の失敗）はそのまま送出する。ツールの失敗は送出せず ToolResult(is_error=True) にする。
    """
    messages = list(chat.messages)
    added: list[dict] = []
    total = Usage(0, 0)
    definitions = tool_definitions(tools)  # 実行できるツールと、LLM に見せるツールを同じ登録簿から作る
    for step in range(1, limits.max_steps + 1):
        texts: list[str] = []
        calls: list[ToolCall] = []
        done: Done | None = None
        request = replace(chat, messages=list(messages), tools=definitions)  # 送った後で書き換わらないよう写しを渡す
        upstream = provider.stream(request)
        try:
            async for ev in upstream:
                if isinstance(ev, Done):
                    done = ev
                    continue  # Done はステップの終わり。ループ全体の終わりは LoopDone で知らせる
                if isinstance(ev, TextDelta):
                    texts.append(ev.text)
                elif isinstance(ev, ToolCallDone):
                    calls.append(ToolCall(ev.id, ev.name, ev.input))  # 引数の JSON がそろったのはここ
                yield ev
        finally:
            await close_upstream(upstream)  # 途中で止められても上流の接続を必ず閉じる
        assert done is not None  # 差し替え層は Done を出すか ProviderError を送出する
        total = add_usage(total, done.usage)
        yield StepDone(step, done.stop_reason, done.usage)
        assistant = {"role": "assistant", "content": assistant_blocks(texts, calls)}
        if done.stop_reason != "tool_use" or not calls:
            added.append(assistant)
            yield LoopDone(done.stop_reason, total, step, added)
            return
        results: list[ToolResult] = []
        for call in calls:  # 1つずつ順に実行する（並行実行は練習問題で扱う）
            if step == limits.max_steps:
                result = _error(call, STEP_LIMIT)  # 結果を読む LLM 呼び出しが無いので実行しない
            else:
                result = await execute_tool(call, ctx, tools=tools, limits=limits)
            results.append(result)
            yield result
        # tool_use を含む assistant と、その結果だけの user を必ず組で足す（組を分断しない）
        user = {"role": "user", "content": [tool_result_block(r) for r in results]}
        messages += [assistant, user]
        added += [assistant, user]
    yield LoopDone("max_steps", total, limits.max_steps, added)
