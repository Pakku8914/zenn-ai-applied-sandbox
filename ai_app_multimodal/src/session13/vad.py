"""VAD（発話区間検出）で、20ms ずつ届く PCM の流れから1発話を切り出す（セッション10からそのままコピー）。

webrtcvad は 10・20・30ms のフレームしか受け付けない。上りの 20ms をそのまま使わずに 30ms へ組み直すのは、
Silero VAD と比べて採用を決めた設定（30ms・aggressiveness 2）と同じ条件で判定するため（20ms の3通 → 30ms の2フレーム）。
判定はフレームの数だけで行い、時計は使わない（同じ音なら必ず同じ結果になる）。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import webrtcvad

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2     # 960 バイト（480 サンプル × 2 バイト）
AGGRESSIVENESS = 2         # 0（ゆるい）〜 3（厳しい）。厳しいほど雑音を声と見なしにくい
START_MS = 150             # 声が 150ms 続いたら話し始め（雑音を 0.09 秒ほど声と誤る程度では始めない）
END_SILENCE_MS = 600       # 声のないフレームが 600ms 続いたら話し終わり
PREROLL_MS = 300           # 話し始めと判定する前の 300ms も発話に含める（語頭が欠けないように）
MAX_UTTERANCE_MS = 15000   # 1発話の上限。雑音が鳴り続けても、ここで打ち切る


@dataclass(frozen=True)
class VadEvent:
    kind: str                  # "speech_start" か "speech_end"
    frame: int                 # 判定したフレームの番号（0 から数える。1つ 30ms）
    audio: bytes = b""         # speech_end のときだけ、1発話ぶんの PCM 16bit


class UtteranceDetector:
    def __init__(
        self,
        is_speech: Callable[[bytes], bool] | None = None,
        *,
        start_ms: int = START_MS,
        end_silence_ms: int = END_SILENCE_MS,
        preroll_ms: int = PREROLL_MS,
        max_ms: int = MAX_UTTERANCE_MS,
    ) -> None:
        if is_speech is None:                       # 検証では、決まった答えを返す関数に差し替える
            vad = webrtcvad.Vad(AGGRESSIVENESS)

            def is_speech(frame: bytes) -> bool:
                return vad.is_speech(frame, SAMPLE_RATE)

        self._is_speech = is_speech
        self.start_frames = start_ms // FRAME_MS
        self.end_frames = end_silence_ms // FRAME_MS
        self.max_frames = max_ms // FRAME_MS
        self._pre: deque[bytes] = deque(maxlen=preroll_ms // FRAME_MS + self.start_frames)
        self.frame_index = -1          # 最後に判定したフレームの番号
        self.last_voiced_frame = -1    # 最後に「声あり」だったフレームの番号
        self.reset()

    def reset(self) -> None:
        """溜めた音と状態を捨て、話し始めを待つ状態に戻す（フレームの番号は続きから数える）。"""
        self._buf = b""
        self._pre.clear()
        self._utt: list[bytes] = []
        self.in_speech = False
        self._voiced_run = 0
        self._silent_run = 0

    def push(self, pcm: bytes) -> list[VadEvent]:
        """届いた PCM を足し、30ms のフレームがそろうたびに判定する。起きたイベントを返す。"""
        self._buf += pcm
        events: list[VadEvent] = []
        while len(self._buf) >= FRAME_BYTES:
            frame, self._buf = self._buf[:FRAME_BYTES], self._buf[FRAME_BYTES:]
            event = self._step(frame)
            if event is not None:
                events.append(event)
        return events

    def _step(self, frame: bytes) -> VadEvent | None:
        self.frame_index += 1
        voiced = self._is_speech(frame)
        if voiced:
            self.last_voiced_frame = self.frame_index
        if not self.in_speech:
            self._pre.append(frame)
            self._voiced_run = self._voiced_run + 1 if voiced else 0
            if self._voiced_run < self.start_frames:
                return None
            self.in_speech, self._silent_run = True, 0
            self._utt = list(self._pre)             # 話し始める前の 300ms と、判定に使った 150ms を含める
            self._pre.clear()
            return VadEvent("speech_start", self.frame_index)
        self._utt.append(frame)
        self._silent_run = 0 if voiced else self._silent_run + 1
        if self._silent_run < self.end_frames and len(self._utt) < self.max_frames:
            return None
        audio = b"".join(self._utt)
        self._utt, self.in_speech, self._voiced_run = [], False, 0
        return VadEvent("speech_end", self.frame_index, audio)
