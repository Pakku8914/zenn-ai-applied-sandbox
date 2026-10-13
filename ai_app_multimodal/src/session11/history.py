"""1本の接続の会話履歴（Anthropic 形式の messages）。

- assistant の発言は「ユーザーに聞かせた文」だけを残す。割り込まれたら、末尾に INTERRUPTED_NOTE を付ける
- 返答の前に割り込まれた（thinking）ときは assistant を残さない。次の user 発言は、前の user 発言に続けて1つにまとめる
  （user と assistant が交互に並ぶ形を保つ）
"""

from __future__ import annotations

INTERRUPTED_NOTE = "（ここでユーザーが話し始めたため、読み上げを止めました。この先は伝わっていません）"


class Conversation:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def add_user(self, text: str) -> None:
        if self.messages and self.messages[-1]["role"] == "user":     # 返事を聞く前に言い足した
            self.messages[-1] = {"role": "user", "content": self.messages[-1]["content"] + "\n" + text}
        else:
            self.messages.append({"role": "user", "content": text})

    def add_assistant(self, sentences: list[str], *, interrupted: bool) -> None:
        lines = list(sentences)
        if interrupted:
            lines.append(INTERRUPTED_NOTE)            # 聞き終えた文が 0 でも、途中で止めたことは残す
        if lines:
            self.messages.append({"role": "assistant", "content": "\n".join(lines)})

    def snapshot(self) -> list[dict]:
        """LLM に渡す写し（渡したあとに履歴が伸びても、渡した中身は変わらない）。"""
        return [dict(m) for m in self.messages]
