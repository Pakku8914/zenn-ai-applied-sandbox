"""送った音声を、クライアントがいつ鳴らし終えるかを見積もる（セッション11の playback.py の写し）。

    文 i の鳴り始め ＝ max(送った時刻 ＋ lead, 文 i-1 の鳴り終わり)
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
        start = sent_at + self.lead_s
        if self.ends:
            start = max(start, self.ends[-1])
        self.texts.append(text)
        self.starts.append(start)
        self.ends.append(start + seconds)

    def heard_count(self, now: float) -> int:
        return bisect_right(self.ends, now)

    def heard(self, now: float) -> list[str]:
        return self.texts[:self.heard_count(now)]

    def finished(self, now: float) -> bool:
        return self.heard_count(now) == len(self.ends)
