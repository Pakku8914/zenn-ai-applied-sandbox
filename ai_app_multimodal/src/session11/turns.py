"""ターンの状態機械。状態は3つで、移ってよい組み合わせを表で決める。

    listening（聞いている）→ thinking（考えている）   … 話し終わりを検出して、ターンを始めた
    thinking → speaking（話している）                 … 最初の音声（WAV）を送った
    thinking → listening                              … 音声を1つも送らずに終わった（聞き取れなかった・障害）か、割り込まれた
    speaking → listening                              … クライアントが鳴らし終える見込みの時刻を過ぎたか、割り込まれた

表に無い移り方（listening → speaking など）は、コードの誤りなので ValueError にする。
"""

from __future__ import annotations

from enum import StrEnum


class TurnState(StrEnum):
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


ALLOWED = {
    (TurnState.LISTENING, TurnState.THINKING),
    (TurnState.THINKING, TurnState.SPEAKING),
    (TurnState.THINKING, TurnState.LISTENING),
    (TurnState.SPEAKING, TurnState.LISTENING),
}


class TurnMachine:
    def __init__(self) -> None:
        self.state = TurnState.LISTENING
        self.log: list[tuple[str, str]] = [(self.state.value, "connect")]   # (移った先, 理由) の記録

    def to(self, new: TurnState, reason: str) -> None:
        if (self.state, new) not in ALLOWED:
            raise ValueError(f"{self.state} から {new} へは移れません（{reason}）")
        self.state = new
        self.log.append((new.value, reason))
