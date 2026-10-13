"""受け取った WAV を確かめて、音声認識に渡せる 16kHz・モノラル・float32 にする。音声はファイルに書かない。"""

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
    """受付で断る理由。HTTP のステータスとエラーの種別を持たせ、エンドポイントでそのまま返す。"""

    def __init__(self, status: int, type_: str, message: str) -> None:
        super().__init__(message)
        self.status, self.type, self.message = status, type_, message


def looks_like_wav(raw: bytes) -> bool:
    """先頭12バイトが RIFF....WAVE か。ファイル名や Content-Type ではなく中身の目印を見る。"""
    return len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"


def lowpass(audio: np.ndarray, rate: int, cutoff_hz: float, taps: int = 101) -> np.ndarray:
    """cutoff_hz より高い音を弱める（窓付き sinc の FIR フィルタ）。間引く前にかけて折り返し雑音を防ぐ。"""
    n = np.arange(taps) - (taps - 1) / 2
    fc = cutoff_hz / rate
    h = 2 * fc * np.sinc(2 * fc * n) * np.hamming(taps)
    h /= h.sum()
    half = (taps - 1) // 2
    return np.convolve(audio, h)[half:half + len(audio)].astype(np.float32)


def to_16k_mono(audio: np.ndarray, rate: int, target: int = TARGET_RATE) -> np.ndarray:
    """モノラルの float32 配列のサンプリングレートを target に変える。サンプル数は round(元の数 × target ÷ rate)。"""
    if rate == target:
        return audio.astype(np.float32, copy=False)
    if rate > target:
        audio = lowpass(audio, rate, cutoff_hz=target / 2 * 0.9)   # 新しいレートで表せる上限（8kHz）の少し手前で切る
    n_out = round(len(audio) * target / rate)
    t_in = np.arange(len(audio)) / rate
    t_out = np.arange(n_out) / target
    return np.interp(t_out, t_in, audio).astype(np.float32)


def decode_wav(raw: bytes) -> np.ndarray:
    """WAV のバイト列 → 16kHz モノラルの float32 配列。受け付けられなければ AudioRejected。"""
    if not looks_like_wav(raw):
        raise AudioRejected(415, "unsupported_media", UNSUPPORTED)
    try:
        audio, rate = wav_to_float32(raw)       # PCM 16bit 以外は ValueError。ステレオは左右を平均してモノラルにする
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
