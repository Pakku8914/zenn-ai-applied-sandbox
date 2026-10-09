"""入力トークン数を数える。count_tokens は Anthropic 固有の機能なので、差し替え層とは別の口にする。"""

from __future__ import annotations

import json
import math
from typing import Any, Protocol

import anthropic

from .providers import translate_error


class TokenCounter(Protocol):
    async def count(self, messages: list[dict], system: str | None = None,
                    tools: list[dict] | None = None) -> int: ...


class AnthropicTokenCounter:
    """POST /v1/messages/count_tokens で数える（本物の API でも mockllm でも同じ呼び方）。"""

    def __init__(self, client: anthropic.AsyncAnthropic, *, model: str) -> None:
        self._client = client
        self._model = model

    async def count(self, messages: list[dict], system: str | None = None,
                    tools: list[dict] | None = None) -> int:
        params: dict[str, Any] = {"model": self._model, "messages": messages}
        if system:
            params["system"] = system
        if tools:
            params["tools"] = tools
        try:
            result = await self._client.messages.count_tokens(**params)
        except anthropic.APIError as e:
            raise translate_error("anthropic", e) from e
        return result.input_tokens


def _text_tokens(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / 3) if text else 0


def _json_tokens(value: object) -> int:
    return _text_tokens(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _block_tokens(block: dict) -> int:
    kind = block.get("type")
    if kind == "text":
        return _text_tokens(block.get("text", ""))
    if kind == "tool_use":
        return _text_tokens(block.get("name", "")) + _json_tokens(block.get("input", {}))
    if kind == "tool_result":
        content = block.get("content", "")
        return _text_tokens(content) if isinstance(content, str) else sum(_block_tokens(b) for b in content)
    return 0


class ApproxTokenCounter:
    """手元で数える近似（mockllm と同じ式）。本物のトークナイザとは一致しないので、本番では安全率を掛ける。"""

    def __init__(self, safety: float = 1.0) -> None:
        self._safety = safety

    async def count(self, messages: list[dict], system: str | None = None,
                    tools: list[dict] | None = None) -> int:
        total = 4 + _text_tokens(system or "") + sum(_json_tokens(t) for t in tools or [])
        for m in messages:
            content = m["content"]
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
            total += 3 + sum(_block_tokens(b) for b in blocks)
        return math.ceil(total * self._safety)
