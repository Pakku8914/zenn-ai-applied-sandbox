"""ターンの状態機械（セッション11の turns.py の写し）。listening → thinking → speaking → listening。"""

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
        self.log: list[tuple[str, str]] = [(self.state.value, "connect")]

    def to(self, new: TurnState, reason: str) -> None:
        if (self.state, new) not in ALLOWED:
            raise ValueError(f"{self.state} から {new} へは移れません（{reason}）")
        self.state = new
        self.log.append((new.value, reason))
