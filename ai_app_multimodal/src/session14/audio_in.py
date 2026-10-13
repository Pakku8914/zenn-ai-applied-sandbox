"""受け取った WAV を確かめて、音声認識に渡せる 16kHz・モノラル・float32 にする（セッション8の audio_in.py のコピー）。"""

from __future__ import annotations

import wave

import numpy as np

from kondate.audio import wav_to_float32
from kondate.settings import get_settings

TARGET_RATE = get_settings().stt_sample_rate     # 16000
MIN_SECONDS = 0.1
MAX_SECONDS = 60.0
UNSUPPORTED = "WAV（PCM 16bit）の音声を送ってください"


class AudioRejected(Exception):
    def __init__(self, status: int, type_: str, message: str) -> None:
        super().__init__(message)
        self.status, self.type, self.message = status, type_, message


def looks_like_wav(raw: bytes) -> bool:
    return len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"


def lowpass(audio: np.ndarray, rate: int, cutoff_hz: float, taps: int = 101) -> np.ndarray:
    n = np.arange(taps) - (taps - 1) / 2
    fc = cutoff_hz / rate
    h = 2 * fc * np.sinc(2 * fc * n) * np.hamming(taps)
    h /= h.sum()
    half = (taps - 1) // 2
    return np.convolve(audio, h)[half:half + len(audio)].astype(np.float32)


def to_16k_mono(audio: np.ndarray, rate: int, target: int = TARGET_RATE) -> np.ndarray:
    if rate == target:
        return audio.astype(np.float32, copy=False)
    if rate > target:
        audio = lowpass(audio, rate, cutoff_hz=target / 2 * 0.9)
    n_out = round(len(audio) * target / rate)
    t_in = np.arange(len(audio)) / rate
    t_out = np.arange(n_out) / target
    return np.interp(t_out, t_in, audio).astype(np.float32)


def decode_wav(raw: bytes) -> np.ndarray:
    if not looks_like_wav(raw):
        raise AudioRejected(415, "unsupported_media", UNSUPPORTED)
    try:
        audio, rate = wav_to_float32(raw)
    except (wave.Error, EOFError, ValueError):
        raise AudioRejected(415, "unsupported_media", UNSUPPORTED) from None
    if rate <= 0:
        raise AudioRejected(415, "unsupported_media", UNSUPPORTED)
    seconds = len(audio) / rate
    if seconds > MAX_SECONDS:
        raise AudioRejected(413, "too_large", f"音声は {MAX_SECONDS:.0f} 秒以下にしてください")
    if seconds < MIN_SECONDS:
        raise AudioRejected(422, "invalid_request", f"入力値が正しくありません：audio（{MIN_SECONDS} 秒以上の音声を送ってください）")
    return to_16k_mono(audio, rate)
