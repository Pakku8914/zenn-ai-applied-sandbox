"""1ターンの遅延の内訳（セッション10からコピー）。時刻を受け取って差を計算するだけで、時計は呼ばない。

    vad                 最後に「声あり」のフレームを処理した → VAD が話し終わりと判定した
    stt                 話し終わりの判定 → 音声認識の結果が出た（limiter の順番待ちを含む）
    llm_first_sentence  音声認識の結果 → LLM の差分から最初の文が完成した
    tts_first           最初の文が完成した → その文の合成が終わった
    first_audio         最後に「声あり」のフレームを処理した → 最初の音声（WAV）を送り終えた（＝上の4つ＋送信）
"""

from __future__ import annotations

from dataclasses import dataclass

KEYS = ("vad", "stt", "llm_first_sentence", "tts_first", "first_audio")


@dataclass
class TurnTimes:
    last_voice: float
    speech_end: float
    transcript: float | None = None
    first_sentence: float | None = None
    tts_first: float | None = None
    first_audio: float | None = None

    def sentence_ready(self, now: float) -> None:
        """文が完成するたびに呼ぶ。記録するのは最初の1回だけ。"""
        if self.first_sentence is None:
            self.first_sentence = now

    def latency_ms(self) -> dict[str, int | None]:
        """ミリ秒の整数に丸めた内訳。返答しなかったターン（何も聞き取れなかった）では後ろの3つが None。"""

        def ms(start: float | None, end: float | None) -> int | None:
            return None if start is None or end is None else round((end - start) * 1000)

        return {
            "vad": ms(self.last_voice, self.speech_end),
            "stt": ms(self.speech_end, self.transcript),
            "llm_first_sentence": ms(self.transcript, self.first_sentence),
            "tts_first": ms(self.first_sentence, self.tts_first),
            "first_audio": ms(self.last_voice, self.first_audio),
        }
