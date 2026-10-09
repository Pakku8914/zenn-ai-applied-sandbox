"""1往復ぶんの「保存するもの」を決める（このプロジェクトで書く部品）。

保存の原則：
1. DB に残すのは、クライアントへ送ったものだけ（結果を送っていない tool_use は残さない）
2. 往復は必ず assistant の発言で閉じる（tool_result だけの user で終えない）
   - 上限到達：サーバが書いた締めの発言（STEP_LIMIT_NOTE。delta でクライアントにも送る）を stop_reason=max_steps で足す
   - 途中で終わった：その時点までのテキストを status=partial の assistant にして足す（テキストが無ければ空の配列）
3. start で知らせた message_id は、往復の最後に保存する assistant の ID にする
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .loop import LoopDone, LoopEvent, ToolResult, assistant_blocks, tool_result_block
from .providers import TextDelta, ToolCall, ToolCallDone

STEP_LIMIT_NOTE = "（ツールの呼び出しが上限に達したため、ここで回答を終えました。条件を絞って、もう一度質問してください。）"


@dataclass(frozen=True)
class StoredMessage:
    """保存する発言1件。seq は保存するときに repo が振る。"""

    role: str  # user / assistant
    content: list[dict]  # Anthropic 形式の content ブロック
    status: str = "complete"  # complete / partial
    stop_reason: str | None = None  # assistant だけ：tool_use / end_turn / max_tokens / max_steps
    id: str | None = None  # None なら保存するときに UUIDv7 を振る


def text_blocks(text: str) -> list[dict]:
    return [{"type": "text", "text": text}] if text else []


def has_tool_use(content: list[dict]) -> bool:
    return any(b.get("type") == "tool_use" for b in content)


class TurnRecorder:
    """ループのイベントを横で見て、「いま止まったら何を保存するか」にいつでも答えられるようにしておく。"""

    def __init__(self, message_id: str, user_text: str) -> None:
        self.message_id = message_id
        self.user = StoredMessage("user", text_blocks(user_text))
        self.closed: list[StoredMessage] = []  # 結果まで送り終えた組（assistant の tool_use と、tool_result の user）
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
            if len(self._results) == len(self._calls):  # このステップの呼び出しすべてに結果を送った＝組が閉じた
                self.closed += [
                    StoredMessage("assistant", assistant_blocks(self._texts, self._calls), stop_reason="tool_use"),
                    StoredMessage("user", [tool_result_block(r) for r in self._results]),
                ]
                self._texts, self._calls, self._results = [], [], []

    def completed(self, done: LoopDone) -> list[StoredMessage]:
        """done まで届いた往復。ループが返した発言（LoopDone.messages）をそのまま正とする。"""
        rows = [self.user]
        for m in done.messages:
            if m["role"] == "user":
                rows.append(StoredMessage("user", m["content"]))
            else:
                reason = "tool_use" if has_tool_use(m["content"]) else done.stop_reason
                rows.append(StoredMessage("assistant", m["content"], stop_reason=reason))
        if done.stop_reason == "max_steps":  # 最後は tool_result だけの user なので、締めの発言で閉じる
            rows.append(StoredMessage("assistant", text_blocks(STEP_LIMIT_NOTE), stop_reason="max_steps"))
        return self._stamp(rows)

    def interrupted(self) -> list[StoredMessage]:
        """done まで届かなかった往復。閉じた組と、送ったところまでのテキスト（partial）を残す。"""
        partial = StoredMessage("assistant", text_blocks("".join(self._texts)), status="partial")
        return self._stamp([self.user, *self.closed, partial])  # 結果を送っていない tool_use はここで捨てる

    def _stamp(self, rows: list[StoredMessage]) -> list[StoredMessage]:
        last = max(i for i, r in enumerate(rows) if r.role == "assistant")
        rows = list(rows)
        rows[last] = replace(rows[last], id=self.message_id)
        return rows
