"""LLM の差分（ストリーミング）を受け取り、読み上げる文が完成するたびに返す（セッション10からコピー）。

区切りの規則は sentences.split_sentences と同じ。最後まで流して flush すると、全文を split_sentences に渡したときと同じ文の列になる。
"""

from __future__ import annotations

from src.session11.sentences import split_sentences


class SentenceBuffer:
    def __init__(self) -> None:
        self._line = ""        # まだ改行が来ていない行（書きかけの行）
        self._sent = 0         # その行から、すでに返した文の数

    def feed(self, delta: str) -> list[str]:
        """差分を足し、新しく完成した文を返す（無ければ空のリスト）。"""
        self._line += delta
        done: list[str] = []
        while "\n" in self._line:                  # 改行が来た行は、行末まで文が確定している
            line, self._line = self._line.split("\n", 1)
            done += split_sentences(line)[self._sent:]
            self._sent = 0
        pieces = split_sentences(self._line)
        # 書きかけの行の最後の文は、まだ続きが来るかもしれない（「えっ！」のあとに「？」が来るなど）。
        # 後ろで次の文が始まっていれば、その手前までは確定している
        ready = len(pieces) - 1
        if ready > self._sent:
            done += pieces[self._sent:ready]
            self._sent = ready
        return done

    def flush(self) -> list[str]:
        """返答が終わったときに呼び、残りの文を返す。"""
        rest = split_sentences(self._line)[self._sent:]
        self._line, self._sent = "", 0
        return rest
