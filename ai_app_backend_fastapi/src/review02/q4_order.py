"""問題4の解答：Anthropic と OpenAI 互換で、ツールの差分が届く順序の違いを再現し、どこで吸収されるかを確かめる。

本物の SDK のイベントの代わりに、差し替え層が読む属性だけを持つ SimpleNamespace を作り、normalize_* に通す。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Sequence
from types import SimpleNamespace as NS
from typing import Any

from .providers import StreamEvent, ToolCall, ToolCallDelta, ToolCallDone, ToolCallStart

PIECE = 16  # 引数の JSON を何文字ずつ送るか


def pieces(call: ToolCall) -> list[str]:
    raw = json.dumps(call.input, ensure_ascii=False)
    return [raw[i:i + PIECE] for i in range(0, len(raw), PIECE)]


def anthropic_events(text: str, calls: Sequence[ToolCall], *, input_tokens: int = 100,
                     output_tokens: int = 30) -> list[Any]:
    """Anthropic の生イベント。呼び出しは content block ごとに 開始 → 差分 → 終了 の順で1つずつ届く。"""
    evs: list[Any] = [
        NS(type="message_start", message=NS(usage=NS(input_tokens=input_tokens, output_tokens=1))),
        NS(type="content_block_start", index=0, content_block=NS(type="text")),
        NS(type="content_block_delta", index=0, delta=NS(type="text_delta", text=text)),
        NS(type="content_block_stop", index=0),
    ]
    for i, call in enumerate(calls, 1):
        evs.append(NS(type="content_block_start", index=i, content_block=NS(type="tool_use", id=call.id, name=call.name)))
        evs += [NS(type="content_block_delta", index=i, delta=NS(type="input_json_delta", partial_json=p))
                for p in pieces(call)]
        evs.append(NS(type="content_block_stop", index=i))
    evs += [NS(type="message_delta", delta=NS(stop_reason="tool_use"), usage=NS(output_tokens=output_tokens)),
            NS(type="message_stop")]
    return evs


def _chunk(*, content: str | None = None, tool_calls: list[Any] | None = None,
           finish_reason: str | None = None) -> Any:
    return NS(usage=None, choices=[NS(delta=NS(content=content, tool_calls=tool_calls), finish_reason=finish_reason)])


def openai_chunks(text: str, calls: Sequence[ToolCall], *, interleave: bool = True, prompt_tokens: int = 100,
                  completion_tokens: int = 30) -> list[Any]:
    """OpenAI 互換の chat.completion.chunk。呼び出しは index で区別され、終了の合図は finish_reason だけ。"""
    out = [_chunk(content=text)]
    out += [_chunk(tool_calls=[NS(index=i, id=c.id, function=NS(name=c.name, arguments=""))])
            for i, c in enumerate(calls)]  # id と name は各呼び出しの最初の差分にだけ入る
    parts = [pieces(c) for c in calls]
    order: list[tuple[int, str]] = []
    if interleave:  # index で区別できるので、2つの呼び出しの差分が交互に届いてもよい
        for k in range(max(len(ps) for ps in parts)):
            for i, ps in enumerate(parts):
                if k < len(ps):
                    order.append((i, ps[k]))
    else:
        order = [(i, p) for i, ps in enumerate(parts) for p in ps]
    out += [_chunk(tool_calls=[NS(index=i, id=None, function=NS(name=None, arguments=p))]) for i, p in order]
    out.append(_chunk(finish_reason="tool_calls"))
    out.append(NS(usage=NS(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens), choices=[]))
    return out


async def replay(items: Iterable[Any]) -> AsyncIterator[Any]:
    """リストを、SDK のストリームと同じ async の反復にする。"""
    for x in items:
        yield x


def call_order(events: Iterable[StreamEvent]) -> list[str]:
    """ToolCallStart と ToolCallDone が届いた順（例：start:toolu_1 → done:toolu_1 → …）。"""
    return [f"{'start' if isinstance(e, ToolCallStart) else 'done'}:{e.id}"
            for e in events if isinstance(e, (ToolCallStart, ToolCallDone))]


def calls_from_done(events: Iterable[StreamEvent]) -> list[ToolCall]:
    """Good：引数がそろった ToolCallDone だけを見る。届く順序の違いは差し替え層が吸収済み。"""
    return [ToolCall(e.id, e.name, e.input) for e in events if isinstance(e, ToolCallDone)]


def naive_tool_calls(events: Iterable[StreamEvent]) -> list[tuple[str, str]]:
    """Bad（問題文の後輩のコード）：差分は「最後に始まった呼び出し」のものだとみなし、id を見ない。"""
    calls: list[list[str]] = []
    for e in events:
        if isinstance(e, ToolCallStart):
            calls.append([e.id, ""])
        elif isinstance(e, ToolCallDelta):
            calls[-1][1] += e.partial_json
    return [(i, raw) for i, raw in calls]
