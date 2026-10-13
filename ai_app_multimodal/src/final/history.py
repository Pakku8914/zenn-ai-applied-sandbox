"""1本の接続の会話履歴（セッション11の history.py の写し）。assistant は「聞かせた文」だけを残す。"""

from __future__ import annotations

INTERRUPTED_NOTE = "（ここでユーザーが話し始めたため、読み上げを止めました。この先は伝わっていません）"


class Conversation:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def add_user(self, text: str) -> None:
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages[-1] = {"role": "user", "content": self.messages[-1]["content"] + "\n" + text}
        else:
            self.messages.append({"role": "user", "content": text})

    def add_assistant(self, sentences: list[str], *, interrupted: bool) -> None:
        lines = list(sentences)
        if interrupted:
            lines.append(INTERRUPTED_NOTE)
        if lines:
            self.messages.append({"role": "assistant", "content": "\n".join(lines)})

    def snapshot(self) -> list[dict]:
        return [dict(m) for m in self.messages]
