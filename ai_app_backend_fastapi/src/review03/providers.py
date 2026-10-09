"""プロバイダ差し替え層（API契約②）。session11/providers.py から、この章の検証で使う部分だけを写したもの。

本物の SDK を呼ぶ AnthropicProvider・OpenAIProvider と、SDK の例外の翻訳（translate_error）は省いた。
復習3の検証は、上流をすべて FakeProvider（台本どおりに返す偽物）にして行う。
本番の経路には session11 の版をそのまま使う（型と ProviderError はここと同じ）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------- 契約の型


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True)
class ChatRequest:
    messages: list[dict]  # Anthropic 形式を正とする
    system: str | None = None
    tools: list[dict] = field(default_factory=list)  # Anthropic 形式（name・description・input_schema）
    max_tokens: int = 1024
    model: str | None = None  # None ならプロバイダの既定モデル


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass(frozen=True)
class ChatResult:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str  # Anthropic の値（end_turn / tool_use / max_tokens）
    usage: Usage
    request_id: str | None  # 上流のリクエスト ID（問い合わせに使う）


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCallStart:
    id: str
    name: str


@dataclass(frozen=True)
class ToolCallDelta:
    id: str
    partial_json: str


@dataclass(frozen=True)
class ToolCallDone:
    id: str
    name: str
    input: dict


@dataclass(frozen=True)
class Done:
    stop_reason: str
    usage: Usage


StreamEvent = TextDelta | ToolCallStart | ToolCallDelta | ToolCallDone | Done


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def complete(self, req: ChatRequest) -> ChatResult: ...

    # async def にしない：async ジェネレータ関数は「呼ぶと AsyncIterator を返す普通の関数」として型が合う
    def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]: ...


# ---------------------------------------------------------------- 例外をそろえる


class ProviderError(Exception):
    """SDK ごとに違う例外を1つの型にそろえたもの。上流の生のエラー文は持たない（__cause__ に残る）。"""

    RETRYABLE = frozenset({"rate_limited", "overloaded", "server_error", "timeout", "connection"})

    def __init__(self, kind: str, *, provider: str, status_code: int | None = None,
                 request_id: str | None = None, retry_after: int | None = None) -> None:
        super().__init__(f"{provider}: {kind}")
        self.kind = kind
        self.provider = provider
        self.status_code = status_code
        self.request_id = request_id
        self.retry_after = retry_after  # 429 のとき上流が示した待ち秒数（不明なら None）

    @property
    def retryable(self) -> bool:
        # 目安。実際に再試行するか・別のプロバイダへ切り替えるかは呼び出し側が決める
        return self.kind in self.RETRYABLE


# ---------------------------------------------------------------- 偽物（台本どおりに返す）

FakeItem = StreamEvent | BaseException


def accumulate(events: Iterable[StreamEvent], *, request_id: str | None = None) -> ChatResult:
    """stream() のイベント列を畳んで ChatResult にする（complete() と同じ形になる）。"""
    texts: list[str] = []
    calls: list[ToolCall] = []
    done: Done | None = None
    for ev in events:
        if isinstance(ev, TextDelta):
            texts.append(ev.text)
        elif isinstance(ev, ToolCallDone):
            calls.append(ToolCall(ev.id, ev.name, ev.input))
        elif isinstance(ev, Done):
            done = ev
    if done is None:
        raise ValueError("Done イベントがありません（ストリームが途中で終わっています）")
    return ChatResult("".join(texts), calls, done.stop_reason, done.usage, request_id)


def fake_script(text: str = "", *, tool_calls: Sequence[ToolCall] = (), usage: Usage = Usage(0, 0),
                stop_reason: str | None = None, chunk_chars: int = 6) -> list[StreamEvent]:
    """FakeProvider の台本を作る。テキストは chunk_chars 文字ずつ、ツールの引数は16文字ずつに切る。"""
    events: list[StreamEvent] = [TextDelta(text[i:i + chunk_chars]) for i in range(0, len(text), chunk_chars)]
    for call in tool_calls:
        raw = json.dumps(call.input, ensure_ascii=False)
        events.append(ToolCallStart(call.id, call.name))
        events += [ToolCallDelta(call.id, raw[i:i + 16]) for i in range(0, len(raw), 16)]
        events.append(ToolCallDone(call.id, call.name, call.input))
    events.append(Done(stop_reason or ("tool_use" if tool_calls else "end_turn"), usage))
    return events


class FakeProvider:
    """台本どおりのイベントを返すプロバイダ。台本は呼ばれるたびに1つずつ使い、最後の1つは使い回す。

    台本に例外を混ぜると、その位置で送出する（失敗の試験に使う）。
    """

    name = "fake"

    def __init__(self, *scripts: Sequence[FakeItem]) -> None:
        if not scripts:
            raise ValueError("台本を1つ以上渡してください")
        self._scripts = list(scripts)
        self.requests: list[ChatRequest] = []

    def _next(self, req: ChatRequest) -> Sequence[FakeItem]:
        self.requests.append(req)
        return self._scripts.pop(0) if len(self._scripts) > 1 else self._scripts[0]

    async def complete(self, req: ChatRequest) -> ChatResult:
        script = self._next(req)
        for item in script:
            if isinstance(item, BaseException):
                raise item
        return accumulate(script, request_id=f"req_fake_{len(self.requests):06d}")  # type: ignore[arg-type]

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        for item in self._next(req):
            if isinstance(item, BaseException):
                raise item
            yield item
