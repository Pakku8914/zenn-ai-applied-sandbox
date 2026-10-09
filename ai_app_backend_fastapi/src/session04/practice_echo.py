"""練習問題1の解答：最後の user の発言をそのまま返す EchoProvider（SDK を1つも import しない）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .providers import ChatRequest, ChatResult, Done, StreamEvent, TextDelta, Usage, accumulate


def last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m["role"] != "user":
            continue
        content = m["content"]
        if isinstance(content, str):
            return content
        return "".join(b.get("text", "") for b in content if b.get("type") == "text")
    return ""


class EchoProvider:
    name = "echo"

    def __init__(self, chunk_chars: int = 6) -> None:
        self._chunk = chunk_chars

    def _events(self, req: ChatRequest) -> list[StreamEvent]:
        text = last_user_text(req.messages)
        events: list[StreamEvent] = [TextDelta(text[i:i + self._chunk]) for i in range(0, len(text), self._chunk)]
        events.append(Done("end_turn", Usage(input_tokens=len(text), output_tokens=len(text))))
        return events

    async def complete(self, req: ChatRequest) -> ChatResult:
        return accumulate(self._events(req))

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        for ev in self._events(req):
            yield ev
