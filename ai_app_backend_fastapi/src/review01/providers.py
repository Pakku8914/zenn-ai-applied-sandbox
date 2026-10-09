"""プロバイダ差し替え層（API契約②）。session04/providers.py のコピーに、復習1の問題3の変更を足したもの。

変更点は2つだけ：
- ProviderError に retry_after（429 の待ち秒数。分からなければ None）を持たせる
- translate_error が 429 のときに上流の retry-after ヘッダを読んで retry_after に入れる
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import anthropic
import httpx2
import openai

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
        self.retry_after = retry_after  # 復習1で追加：429 のとき上流が示した待ち秒数（不明なら None）

    @property
    def retryable(self) -> bool:
        # 目安。実際に再試行するか・別のプロバイダへ切り替えるかは呼び出し側が決める
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
    """上流の応答の retry-after を秒の整数で返す。ヘッダが無い・日時の形式なら None（既定値は呼び出し側が決める）。"""
    response = getattr(e, "response", None)  # 応答を受け取った例外（APIStatusError）にだけある
    raw = response.headers.get("retry-after", "") if response is not None else ""
    return int(raw) if raw.isdigit() else None


def translate_error(provider: str, e: Exception) -> ProviderError:
    status = getattr(e, "status_code", None)
    if isinstance(e, (anthropic.APITimeoutError, openai.APITimeoutError)):
        kind = "timeout"
    elif isinstance(e, (anthropic.APIConnectionError, openai.APIConnectionError, httpx2.RemoteProtocolError)):
        kind = "connection"  # 途中切断は httpx2 の例外がそのまま上がってくる
    elif status is not None:
        kind = kind_from_status(status)
    else:
        kind = "stream_error"  # openai はストリーム途中の error をステータスなしの APIError で投げる
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
    """SDK の usage を Usage にする。None の項目は base の値を残す（message_delta は累計値の上書き）。"""
    base = base or Usage(0, 0)

    def pick(name: str, old: int) -> int:
        value = getattr(u, name, None)
        return old if value is None else value

    return Usage(pick("input_tokens", base.input_tokens), pick("output_tokens", base.output_tokens),
                 pick("cache_read_input_tokens", base.cache_read_input_tokens),
                 pick("cache_creation_input_tokens", base.cache_creation_input_tokens))


async def normalize_anthropic_stream(events: AsyncIterable[Any]) -> AsyncIterator[StreamEvent]:
    """Anthropic の生イベント（message_start …）を StreamEvent に変える。"""
    usage, stop_reason = Usage(0, 0), None
    tools: dict[int, tuple[str, str, list[str]]] = {}  # content block の index → (id, name, 断片)
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
        raise ProviderError("connection", provider="anthropic")  # message_delta の前に終わった
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


# ---------------------------------------------------------------- OpenAI 互換（/v1/chat/completions）

OPENAI_FINISH_TO_STOP = {"stop": "end_turn", "tool_calls": "tool_use", "function_call": "tool_use",
                         "length": "max_tokens", "content_filter": "refusal"}


def stop_from_openai(finish_reason: str | None) -> str:
    return OPENAI_FINISH_TO_STOP.get(finish_reason or "stop", "end_turn")


def usage_from_openai(u: Any) -> Usage:
    """OpenAI の prompt_tokens はキャッシュ分を含む。Anthropic にそろえて input_tokens から引く。"""
    if u is None:
        return Usage(0, 0)
    cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", None) or 0
    return Usage(input_tokens=u.prompt_tokens - cached, output_tokens=u.completion_tokens,
                 cache_read_input_tokens=cached)


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if b.get("type") == "text")


def to_openai_messages(messages: list[dict], system: str | None = None) -> list[dict]:
    """Anthropic 形式の messages を Chat Completions 形式にする。テキストとツール以外は送れない。"""
    out: list[dict] = [{"role": "system", "content": system}] if system else []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        texts: list[str] = []
        calls: list[dict] = []
        results: list[dict] = []
        for b in content:
            if b["type"] == "text":
                texts.append(b["text"])
            elif b["type"] == "tool_use":
                calls.append({"id": b["id"], "type": "function", "function": {
                    "name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}})
            elif b["type"] == "tool_result":
                results.append({"role": "tool", "tool_call_id": b["tool_use_id"],
                                "content": _text_of(b.get("content", ""))})
            else:
                raise ProviderError("unsupported", provider="openai")
        if m["role"] == "assistant":
            msg: dict = {"role": "assistant", "content": "\n".join(texts) or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:
            out.extend(results)  # tool の結果は、呼び出しを含む assistant の直後に置く
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
    return out


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {
        "name": t["name"], "description": t.get("description", ""),
        "parameters": t.get("input_schema", {"type": "object", "properties": {}})}} for t in tools]


async def normalize_openai_stream(chunks: AsyncIterable[Any]) -> AsyncIterator[StreamEvent]:
    """chat.completion.chunk の列を StreamEvent に変える。ツールの差分は index で束ねる。"""
    usage, stop_reason = Usage(0, 0), None
    tools: dict[int, tuple[str, str, list[str]]] = {}  # tool_calls の index → (id, name, 断片)
    async for chunk in chunks:
        if getattr(chunk, "usage", None) is not None:
            usage = usage_from_openai(chunk.usage)  # include_usage のとき、choices が空の最後のチャンクに入る
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        if choice.delta.content:
            yield TextDelta(choice.delta.content)
        for tc in choice.delta.tool_calls or []:
            if tc.index not in tools:  # id と name は、各呼び出しの最初の差分にだけ入っている
                tools[tc.index] = (tc.id, tc.function.name, [])
                yield ToolCallStart(tc.id, tc.function.name)
            piece = tc.function.arguments if tc.function else None
            if piece:
                tools[tc.index][2].append(piece)
                yield ToolCallDelta(tools[tc.index][0], piece)
        if choice.finish_reason is not None:
            stop_reason = stop_from_openai(choice.finish_reason)
            for tool_id, name, parts in tools.values():  # 呼び出しごとの終了イベントが無いので、ここで閉じる
                yield ToolCallDone(tool_id, name, parse_tool_input("".join(parts), "openai"))
            tools.clear()
    if stop_reason is None:
        raise ProviderError("connection", provider="openai")  # finish_reason の前に終わった
    yield Done(stop_reason, usage)


class OpenAIProvider:
    name = "openai"

    def __init__(self, client: openai.AsyncOpenAI, *, default_model: str) -> None:
        self._client = client
        self._model = default_model

    def _params(self, req: ChatRequest) -> dict[str, Any]:
        params: dict[str, Any] = {"model": req.model or self._model, "max_completion_tokens": req.max_tokens,
                                  "messages": to_openai_messages(req.messages, req.system)}
        if req.tools:
            params["tools"] = to_openai_tools(req.tools)
        return params

    async def complete(self, req: ChatRequest) -> ChatResult:
        try:
            resp = await self._client.chat.completions.create(**self._params(req))
        except openai.APIError as e:
            raise translate_error(self.name, e) from e
        choice = resp.choices[0]
        return ChatResult(
            text=choice.message.content or "",
            tool_calls=[ToolCall(tc.id, tc.function.name, parse_tool_input(tc.function.arguments, self.name))
                        for tc in choice.message.tool_calls or []],
            stop_reason=stop_from_openai(choice.finish_reason),
            usage=usage_from_openai(resp.usage),
            request_id=resp._request_id,
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        # include_usage を付けないと、ストリーミングでは usage が1度も届かない
        params = {**self._params(req), "stream": True, "stream_options": {"include_usage": True}}
        try:
            async with await self._client.chat.completions.create(**params) as raw:
                async for ev in normalize_openai_stream(raw):
                    yield ev
        except (openai.APIError, httpx2.RemoteProtocolError) as e:
            raise translate_error(self.name, e) from e


# ---------------------------------------------------------------- Fake とテストの小道具

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


def assistant_message(result: ChatResult) -> dict:
    """ChatResult を、次のリクエストの messages に足す Anthropic 形式の assistant メッセージにする。"""
    blocks: list[dict] = [{"type": "text", "text": result.text}] if result.text else []
    blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in result.tool_calls]
    return {"role": "assistant", "content": blocks}


@asynccontextmanager
async def open_provider(name: str, *, model: str, **client_options: Any) -> AsyncIterator[LLMProvider]:
    """名前からプロバイダを作り、抜けるときに SDK のクライアントを閉じる。client_options は SDK にそのまま渡す。"""
    client: anthropic.AsyncAnthropic | openai.AsyncOpenAI
    provider: LLMProvider
    if name == "anthropic":
        client = anthropic.AsyncAnthropic(**client_options)
        provider = AnthropicProvider(client, default_model=model)
    elif name == "openai":
        client = openai.AsyncOpenAI(**client_options)
        provider = OpenAIProvider(client, default_model=model)
    else:
        raise ValueError(f"未知のプロバイダです: {name}")
    try:
        yield provider
    finally:
        await client.close()
