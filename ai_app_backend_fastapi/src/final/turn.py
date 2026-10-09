"""1往復ぶんの「保存するもの」を決める。mid01/turn.py のコピー（user の発言をブロックの配列で受け取る点だけ変えた）。

保存の原則（mid01 と同じ）：
1. DB に残すのは、クライアントへ送ったものだけ（結果を送っていない tool_use は残さない）
2. 往復は必ず assistant の発言で閉じる（上限到達は締めの発言、途中で終わったら partial の assistant）
3. start で知らせた messageId は、往復の最後に保存する assistant の ID にする
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .loop import LoopDone, LoopEvent, ToolResult, assistant_blocks, tool_result_block
from .providers import TextDelta, ToolCall, ToolCallDone

STEP_LIMIT_NOTE = "（ツールの呼び出しが上限に達したため、ここで回答を終えました。条件を絞って、もう一度質問してください。）"


@dataclass(frozen=True)
class StoredMessage:
    role: str  # user / assistant
    content: list[dict]  # Anthropic 形式の content ブロック
    status: str = "complete"  # complete / partial
    stop_reason: str | None = None
    id: str | None = None


def text_blocks(text: str) -> list[dict]:
    return [{"type": "text", "text": text}] if text else []


def has_tool_use(content: list[dict]) -> bool:
    return any(b.get("type") == "tool_use" for b in content)


class TurnRecorder:
    """ループのイベントを横で見て、「いま止まったら何を保存するか」にいつでも答えられるようにしておく。"""

    def __init__(self, message_id: str, user_content: list[dict]) -> None:
        self.message_id = message_id
        self.user = StoredMessage("user", user_content)
        self.closed: list[StoredMessage] = []
        self._texts: list[str] = []
        self._calls: list[ToolCall] = []
        self._results: list[ToolResult] = []

    def feed(self, ev: LoopEvent) -> None:
        if isinstance(ev, TextDelta):
            self._texts.append(ev.text)
        elif isinstance(ev, ToolCallDone):
            self._calls.append(ToolCall(ev.id, ev.name, ev.input))
        elif isinstance(ev, ToolResult):
            self._results.append(ev)
            if len(self._results) == len(self._calls):
                self.closed += [
                    StoredMessage("assistant", assistant_blocks(self._texts, self._calls), stop_reason="tool_use"),
                    StoredMessage("user", [tool_result_block(r) for r in self._results]),
                ]
                self._texts, self._calls, self._results = [], [], []

    def completed(self, done: LoopDone) -> list[StoredMessage]:
        rows = [self.user]
        for m in done.messages:
            if m["role"] == "user":
                rows.append(StoredMessage("user", m["content"]))
            else:
                reason = "tool_use" if has_tool_use(m["content"]) else done.stop_reason
                rows.append(StoredMessage("assistant", m["content"], stop_reason=reason))
        if done.stop_reason == "max_steps":
            rows.append(StoredMessage("assistant", text_blocks(STEP_LIMIT_NOTE), stop_reason="max_steps"))
        return self._stamp(rows)

    def interrupted(self) -> list[StoredMessage]:
        partial = StoredMessage("assistant", text_blocks("".join(self._texts)), status="partial")
        return self._stamp([self.user, *self.closed, partial])

    def _stamp(self, rows: list[StoredMessage]) -> list[StoredMessage]:
        last = max(i for i, r in enumerate(rows) if r.role == "assistant")
        rows = list(rows)
        rows[last] = replace(rows[last], id=self.message_id)
        return rows
