"""プロバイダ差し替え層（①バックエンド編 API契約② の最小版）。

アプリは LLMProvider（Protocol）だけに依存し、SDK の型を直接触らない。
messages は Anthropic 形式（content block の配列）を正とする。画像は image ブロック、PDF は document ブロック。

③で足したもの（①の契約を壊さない拡張）：ChatRequest.output_schema
  JSON Schema を渡すと構造化出力（Anthropic は output_config.format）で応答させる。応答の検証は呼び出し側で行う。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from typing import Protocol

from anthropic import AsyncAnthropic

from kondate.settings import get_settings


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True)
class ChatRequest:
    messages: list[dict]
    system: str | None = None
    tools: list[dict] = field(default_factory=list)
    max_tokens: int = 1024
    model: str | None = None
    output_schema: dict | None = None


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
    request_id: str | None = None


# ストリームのイベント（stop_reason は Anthropic の値に正規化：end_turn / tool_use / max_tokens）
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


class LLMProvider(Protocol):
    name: str

    async def complete(self, req: ChatRequest) -> ChatResult: ...

    def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]: ...


def _usage(u) -> Usage:
    return Usage(
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
    )


class AnthropicProvider:
    """anthropic 1.x の AsyncAnthropic を包む。クライアントはプロセスに1つ作って渡す（lifespan で close する）。"""

    name = "anthropic"

    def __init__(self, client: AsyncAnthropic, default_model: str | None = None) -> None:
        self._client = client
        self._model = default_model or get_settings().llm_model

    def _kwargs(self, req: ChatRequest) -> dict:
        kw: dict = {"model": req.model or self._model, "max_tokens": req.max_tokens, "messages": req.messages}
        if req.system:
            kw["system"] = req.system
        if req.tools:
            kw["tools"] = req.tools
        if req.output_schema:
            kw["output_config"] = {"format": {"type": "json_schema", "schema": req.output_schema}}
        return kw

    async def complete(self, req: ChatRequest) -> ChatResult:
        msg = await self._client.messages.create(**self._kwargs(req))
        text = "".join(b.text for b in msg.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in msg.content if b.type == "tool_use"]
        return ChatResult(text, calls, msg.stop_reason, _usage(msg.usage), getattr(msg, "_request_id", None))

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        tool_ids: dict[int, tuple[str, str]] = {}
        async with self._client.messages.stream(**self._kwargs(req)) as s:
            async for ev in s:
                if ev.type == "content_block_start" and ev.content_block.type == "tool_use":
                    tool_ids[ev.index] = (ev.content_block.id, ev.content_block.name)
                    yield ToolCallStart(ev.content_block.id, ev.content_block.name)
                elif ev.type == "content_block_delta" and ev.delta.type == "text_delta":
                    yield TextDelta(ev.delta.text)
                elif ev.type == "content_block_delta" and ev.delta.type == "input_json_delta":
                    yield ToolCallDelta(tool_ids[ev.index][0], ev.delta.partial_json)
                elif ev.type == "content_block_stop" and ev.index in tool_ids:
                    block = ev.content_block
                    yield ToolCallDone(block.id, block.name, dict(block.input))
            final = await s.get_final_message()
        yield Done(final.stop_reason, _usage(final.usage))


class FakeProvider:
    """決められた結果を順に返す（単体テスト用）。stream はテキストを chunk 文字ずつに分けて返す。"""

    name = "fake"

    def __init__(self, results: Iterable[ChatResult], chunk: int = 6) -> None:
        self._results = list(results)
        self._chunk = chunk
        self.requests: list[ChatRequest] = []

    def _next(self, req: ChatRequest) -> ChatResult:
        self.requests.append(req)
        if not self._results:
            raise RuntimeError("FakeProvider: 用意した結果を使い切りました")
        return self._results.pop(0)

    async def complete(self, req: ChatRequest) -> ChatResult:
        return self._next(req)

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        r = self._next(req)
        for i in range(0, len(r.text), self._chunk):
            yield TextDelta(r.text[i : i + self._chunk])
        for c in r.tool_calls:
            yield ToolCallStart(c.id, c.name)
            yield ToolCallDelta(c.id, json.dumps(c.input, ensure_ascii=False))
            yield ToolCallDone(c.id, c.name, c.input)
        yield Done(r.stop_reason, r.usage)
