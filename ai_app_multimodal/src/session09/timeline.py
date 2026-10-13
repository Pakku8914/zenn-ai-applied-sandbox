"""「最初の音が出るまで」と「文の間の途切れ」を、合成時間と音声の長さから計算する（時計を使わない純粋な計算）。

前提：合成は同時に1本ずつ順に進め、できた文から順に再生する。合成は再生の終わりを待たずに次の文へ進む。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Timeline:
    first_audio: float           # 最初の音が鳴り始める時刻（秒）
    gaps: tuple[float, ...]      # 文と文の間で、再生が止まって待った時間（秒）
    finished: float              # 最後の音が鳴り終わる時刻（秒）


def plan_whole(synth_seconds: float, audio_seconds: float) -> Timeline:
    """全文をまとめて合成してから再生する。"""
    return Timeline(round(synth_seconds, 3), (), round(synth_seconds + audio_seconds, 3))


def plan_sentences(synth: list[float], audio: list[float]) -> Timeline:
    """文ごとに合成し、できた順に再生する。synth[i] は i 文目の合成時間、audio[i] はその音声の長さ。"""
    ready = play_end = 0.0
    first = 0.0
    gaps: list[float] = []
    for i, (s, a) in enumerate(zip(synth, audio, strict=True)):
        ready += s                      # i 文目の合成が終わる時刻
        start = max(ready, play_end)    # 合成が終わっていて、前の文も鳴り終わっていれば再生できる
        if i == 0:
            first = start
        else:
            gaps.append(round(start - play_end, 3))
        play_end = start + a
    return Timeline(round(first, 3), tuple(gaps), round(play_end, 3))
