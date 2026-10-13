"""VAD（発話区間検出）で、20ms ずつ届く PCM の流れから1発話を切り出す（セッション11の vad.py の写し）。"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import webrtcvad

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2     # 960 バイト
AGGRESSIVENESS = 2
START_MS = 150
END_SILENCE_MS = 600
PREROLL_MS = 300
MAX_UTTERANCE_MS = 15000


@dataclass(frozen=True)
class VadEvent:
    kind: str                  # "speech_start" か "speech_end"
    frame: int
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
        if is_speech is None:
            vad = webrtcvad.Vad(AGGRESSIVENESS)

            def is_speech(frame: bytes) -> bool:
                return vad.is_speech(frame, SAMPLE_RATE)

        self._is_speech = is_speech
        self.start_frames = start_ms // FRAME_MS
        self.end_frames = end_silence_ms // FRAME_MS
        self.max_frames = max_ms // FRAME_MS
        self._pre: deque[bytes] = deque(maxlen=preroll_ms // FRAME_MS + self.start_frames)
        self.frame_index = -1
        self.last_voiced_frame = -1
        self.reset()

    def reset(self) -> None:
        self._buf = b""
        self._pre.clear()
        self._utt: list[bytes] = []
        self.in_speech = False
        self._voiced_run = 0
        self._silent_run = 0
        self.voiced_frames = 0

    def push(self, pcm: bytes) -> list[VadEvent]:
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
            self.voiced_frames = self._voiced_run
            self._utt = list(self._pre)
            self._pre.clear()
            return VadEvent("speech_start", self.frame_index)
        self._utt.append(frame)
        if voiced:
            self.voiced_frames += 1
        self._silent_run = 0 if voiced else self._silent_run + 1
        if self._silent_run < self.end_frames and len(self._utt) < self.max_frames:
            return None
        audio = b"".join(self._utt)
        self._utt, self.in_speech, self._voiced_run = [], False, 0
        return VadEvent("speech_end", self.frame_index, audio)
