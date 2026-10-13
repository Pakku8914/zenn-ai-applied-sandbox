"""LLM の差分から、読み上げる文が完成するたびに返す（セッション11の sentence_buffer.py の写し）。"""

from __future__ import annotations

from src.final.sentences import split_sentences


class SentenceBuffer:
    def __init__(self) -> None:
        self._line = ""
        self._sent = 0

    def feed(self, delta: str) -> list[str]:
        self._line += delta
        done: list[str] = []
        while "\n" in self._line:
            line, self._line = self._line.split("\n", 1)
            done += split_sentences(line)[self._sent:]
            self._sent = 0
        pieces = split_sentences(self._line)
        ready = len(pieces) - 1
        if ready > self._sent:
            done += pieces[self._sent:ready]
            self._sent = ready
        return done

    def flush(self) -> list[str]:
        rest = split_sentences(self._line)[self._sent:]
        self._line, self._sent = "", 0
        return rest
