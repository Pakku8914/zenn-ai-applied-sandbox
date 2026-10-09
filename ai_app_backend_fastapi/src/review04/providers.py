"""プロバイダ差し替え層（API契約②）。session13/providers.py から、この復習で使う分だけをコピーしたもの。

省いたもの：OpenAI 互換の実装（経路は Anthropic 互換の primary と light の2つにする）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import anthropic
import httpx2

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
    tools: list[dict] = field(default_factory=list)
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
    stop_reason: str
    usage: Usage
    request_id: str | None


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
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.kind in self.RETRYABLE


def kind_from_status(status: int) -> str:
    if status < 400:
        return "stream_error"  # HTTP 200 で始まったストリームの途中で error が届いた
    if status in (401, 403):
        return "auth"
    if status == 408:
        return "timeout"
    if status == 429:
        return "rate_limited"
    if status in (503, 529):
        return "overloaded"
    return "bad_request" if status < 500 else "server_error"


def retry_after_seconds(e: Exception) -> int | None:
    response = getattr(e, "response", None)
    raw = response.headers.get("retry-after", "") if response is not None else ""
    return int(raw) if raw.isdigit() else None


def translate_error(provider: str, e: Exception) -> ProviderError:
    status = getattr(e, "status_code", None)
    if isinstance(e, anthropic.APITimeoutError):  # APIConnectionError の子なので先に判定する
        kind = "timeout"
    elif isinstance(e, (anthropic.APIConnectionError, httpx2.RemoteProtocolError)):
        kind = "connection"
    elif status is not None:
        kind = kind_from_status(status)
    else:
        kind = "stream_error"
    retry_after = retry_after_seconds(e) if kind == "rate_limited" else None
    return ProviderError(kind, provider=provider, status_code=status, request_id=getattr(e, "request_id", None),
                         retry_after=retry_after)


def parse_tool_input(raw: str, provider: str) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ProviderError("bad_response", provider=provider) from e
    if not isinstance(value, dict):
        raise ProviderError("bad_response", provider=provider)
    return value


# ---------------------------------------------------------------- Anthropic


def _anthropic_usage(u: Any, base: Usage | None = None) -> Usage:
    base = base or Usage(0, 0)

    def pick(name: str, old: int) -> int:
        value = getattr(u, name, None)
        return old if value is None else value

    return Usage(pick("input_tokens", base.input_tokens), pick("output_tokens", base.output_tokens),
                 pick("cache_read_input_tokens", base.cache_read_input_tokens),
                 pick("cache_creation_input_tokens", base.cache_creation_input_tokens))


async def normalize_anthropic_stream(events: AsyncIterable[Any]) -> AsyncIterator[StreamEvent]:
    usage, stop_reason = Usage(0, 0), None
    tools: dict[int, tuple[str, str, list[str]]] = {}
    async for ev in events:
        if ev.type == "message_start":
            usage = _anthropic_usage(ev.message.usage)
        elif ev.type == "content_block_start" and ev.content_block.type == "tool_use":
            tools[ev.index] = (ev.content_block.id, ev.content_block.name, [])
            yield ToolCallStart(ev.content_block.id, ev.content_block.name)
        elif ev.type == "content_block_delta":
            if ev.delta.type == "text_delta" and ev.delta.text:
                yield TextDelta(ev.delta.text)
            elif ev.delta.type == "input_json_delta" and ev.delta.partial_json:
                tool_id, _, parts = tools[ev.index]
                parts.append(ev.delta.partial_json)
                yield ToolCallDelta(tool_id, ev.delta.partial_json)
        elif ev.type == "content_block_stop" and ev.index in tools:
            tool_id, name, parts = tools.pop(ev.index)
            yield ToolCallDone(tool_id, name, parse_tool_input("".join(parts), "anthropic"))
        elif ev.type == "message_delta":
            stop_reason = ev.delta.stop_reason
            usage = _anthropic_usage(ev.usage, usage)
    if stop_reason is None:
        raise ProviderError("connection", provider="anthropic")
    yield Done(stop_reason, usage)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client: anthropic.AsyncAnthropic, *, default_model: str) -> None:
        self._client = client
        self._model = default_model

    def _params(self, req: ChatRequest) -> dict[str, Any]:
        params: dict[str, Any] = {"model": req.model or self._model, "max_tokens": req.max_tokens,
                                  "messages": req.messages}
        if req.system is not None:
            params["system"] = req.system
        if req.tools:
            params["tools"] = req.tools
        return params

    async def complete(self, req: ChatRequest) -> ChatResult:
        try:
            msg = await self._client.messages.create(**self._params(req))
        except anthropic.APIError as e:
            raise translate_error(self.name, e) from e
        return ChatResult(
            text="".join(b.text for b in msg.content if b.type == "text"),
            tool_calls=[ToolCall(b.id, b.name, dict(b.input)) for b in msg.content if b.type == "tool_use"],
            stop_reason=msg.stop_reason or "end_turn",
            usage=_anthropic_usage(msg.usage),
            request_id=msg._request_id,
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        try:
            async with await self._client.messages.create(**self._params(req), stream=True) as raw:
                async for ev in normalize_anthropic_stream(raw):
                    yield ev
        except (anthropic.APIError, httpx2.RemoteProtocolError) as e:
            raise translate_error(self.name, e) from e


# ---------------------------------------------------------------- Fake（台本どおりに返す）

FakeItem = StreamEvent | BaseException


def accumulate(events: Iterable[StreamEvent], *, request_id: str | None = None) -> ChatResult:
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


def fake_script(text: str = "", *, usage: Usage = Usage(0, 0), stop_reason: str = "end_turn",
                chunk_chars: int = 6) -> list[StreamEvent]:
    events: list[StreamEvent] = [TextDelta(text[i:i + chunk_chars]) for i in range(0, len(text), chunk_chars)]
    events.append(Done(stop_reason, usage))
    return events


class FakeProvider:
    """台本どおりのイベントを返すプロバイダ。台本に例外を混ぜると、その位置で送出する。"""

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


@asynccontextmanager
async def open_provider(name: str, *, model: str, **client_options: Any) -> AsyncIterator[LLMProvider]:
    """Anthropic 互換のプロバイダを作り、抜けるときに SDK のクライアントを閉じる。client_options は SDK にそのまま渡す。"""
    if name != "anthropic":
        raise ValueError(f"この復習で使えるのは anthropic だけです: {name}")
    client = anthropic.AsyncAnthropic(**client_options)
    try:
        yield AnthropicProvider(client, default_model=model)
    finally:
        await client.close()
