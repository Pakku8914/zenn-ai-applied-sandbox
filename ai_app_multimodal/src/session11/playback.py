"""送った音声を、クライアントがいつ鳴らし終えるかを見積もる（上りのメッセージを増やさずに「どこまで聞かせたか」を決める）。

クライアント（static/voice.html）は、届いた WAV を順に、前の文が鳴り終わる時刻に予約して鳴らす。それを写して、
    文 i の鳴り始め ＝ max(送った時刻 ＋ lead, 文 i-1 の鳴り終わり)
    文 i の鳴り終わり ＝ 鳴り始め ＋ 文 i の秒数
とする。lead は「送ってから鳴り始めるまで」の見込み（ネットワーク＋WAV の読み込み）。長めに取るほど、
「聞き終えた」と判定するのが遅くなる（＝聞いていない文を聞いたことにしにくい）。時刻は呼び出し側が渡す（時計を持たない）。
"""

from __future__ import annotations

from bisect import bisect_right

PLAYBACK_LEAD_S = 0.3


class PlaybackEstimate:
    def __init__(self, lead_s: float = PLAYBACK_LEAD_S) -> None:
        self.lead_s = lead_s
        self.texts: list[str] = []
        self.starts: list[float] = []
        self.ends: list[float] = []

    def add(self, text: str, seconds: float, sent_at: float) -> None:
        """WAV を1つ送り終えたときに呼ぶ。"""
        start = sent_at + self.lead_s
        if self.ends:
            start = max(start, self.ends[-1])          # 前の文が鳴っている間は、その後ろに並ぶ
        self.texts.append(text)
        self.starts.append(start)
        self.ends.append(start + seconds)

    def heard_count(self, now: float) -> int:
        """now までに鳴り終えた（と見積もった）文の数。＝ まだ鳴り終えていない最初の文の番号。"""
        return bisect_right(self.ends, now)            # ends は小さい順に並んでいる

    def heard(self, now: float) -> list[str]:
        return self.texts[:self.heard_count(now)]

    def finished(self, now: float) -> bool:
        """送った音声を、すべて鳴らし終えたか（1つも送っていなければ True）。"""
        return self.heard_count(now) == len(self.ends)
