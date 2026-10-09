"""UI Message Stream の送出側（AI SDK の UI Message Stream Protocol）。ループのイベントを UI チャンクの dict に変える部品。

- 枠：1チャンク＝ `data: <JSON>\\n\\n`。終端は `data: [DONE]\\n\\n`。`event:` 行は使わない
- ヘッダ：AI SDK の既定（UI_MESSAGE_STREAM_HEADERS）と同じ5個。受信側は検査しないが、送出側は付けておく契約
- 順序：start → (start-step … finish-step)×ステップ数 → data-usage → finish → [DONE]
"""

from __future__ import annotations

import json

from .loop import LoopEvent, StepDone, ToolResult
from .providers import TextDelta, ToolCallDelta, ToolCallDone, ToolCallStart

UI_STREAM_HEADERS = {
    "content-type": "text/event-stream",  # charset を付けない（AI SDK の既定と同じ）
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "x-vercel-ai-ui-message-stream": "v1",
    "x-accel-buffering": "no",
}
DONE_LINE = b"data: [DONE]\n\n"

# 上流の stop_reason（と、こちらの max_steps）→ finish.finishReason（ai@7.0.127 にある値だけを使う）
FINISH_REASONS = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "refusal": "content-filter",
    "max_steps": "other",  # ステップ上限で止めた。締めの文で往復は閉じているので tool-calls にはしない
}


def finish_reason(stop_reason: str) -> str:
    return FINISH_REASONS.get(stop_reason, "other")


def encode(chunk: dict) -> bytes:
    return f"data: {json.dumps(chunk, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()


class UiWriter:
    """ループのイベントを UI チャンクにする。text-start／text-end と start-step／finish-step の対を、ここで閉じる。"""

    def __init__(self) -> None:
        self.text_id: str | None = None
        self.in_step = False
        self._texts = 0

    def _open_step(self) -> list[dict]:
        if self.in_step:
            return []
        self.in_step = True
        return [{"type": "start-step"}]

    def _close_text(self) -> list[dict]:
        if self.text_id is None:
            return []
        chunk = {"type": "text-end", "id": self.text_id}
        self.text_id = None
        return [chunk]

    def feed(self, ev: LoopEvent) -> list[dict]:
        out: list[dict] = []
        if isinstance(ev, TextDelta):
            out += self._open_step()
            if self.text_id is None:
                self._texts += 1
                self.text_id = f"text-{self._texts}"
                out.append({"type": "text-start", "id": self.text_id})
            out.append({"type": "text-delta", "id": self.text_id, "delta": ev.text})
        elif isinstance(ev, ToolCallStart):
            out += self._open_step() + self._close_text()
            out.append({"type": "tool-input-start", "toolCallId": ev.id, "toolName": ev.name})
        elif isinstance(ev, ToolCallDelta):
            out.append({"type": "tool-input-delta", "toolCallId": ev.id, "inputTextDelta": ev.partial_json})
        elif isinstance(ev, ToolCallDone):
            out += self._open_step()
            out.append({"type": "tool-input-available", "toolCallId": ev.id, "toolName": ev.name, "input": ev.input})
        elif isinstance(ev, ToolResult):
            if ev.is_error:
                out.append({"type": "tool-output-error", "toolCallId": ev.id, "errorText": str(ev.output)})
            else:
                out.append({"type": "tool-output-available", "toolCallId": ev.id, "output": ev.output})
        elif isinstance(ev, StepDone):
            out += self._close_text()
            if self.in_step:
                self.in_step = False
                out.append({"type": "finish-step"})
        return out

    def note(self, text: str) -> list[dict]:
        """サーバが書いた締めの文を、1つのステップとして送る（ステップ上限のとき）。"""
        self._texts += 1
        text_id = f"text-{self._texts}"
        return [{"type": "start-step"}, {"type": "text-start", "id": text_id},
                {"type": "text-delta", "id": text_id, "delta": text}, {"type": "text-end", "id": text_id},
                {"type": "finish-step"}]
