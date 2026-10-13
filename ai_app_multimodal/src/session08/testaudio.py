"""検証用の合成音（サイン波）と、その WAV。録音を使わず、長さ・レート・チャンネル・ビット深度を自由に決めて作れる。"""

from __future__ import annotations

import io
import wave

import numpy as np


def tone(freq: float, rate: int, seconds: float, amp: float = 0.3) -> np.ndarray:
    t = np.arange(round(rate * seconds)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def tone_wav(rate: int, seconds: float, *, channels: int = 1, sampwidth: int = 2, freq: float = 440.0) -> bytes:
    mono = tone(freq, rate, seconds)
    if sampwidth == 2:
        samples = (mono * 32767).astype("<i2")
    else:  # 8bit の WAV は符号なし（0〜255）
        samples = ((mono + 1.0) * 127.5).astype(np.uint8)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        wf.writeframes(np.repeat(samples, channels).tobytes())  # 各チャンネルに同じ値を交互に並べる
    return buf.getvalue()
