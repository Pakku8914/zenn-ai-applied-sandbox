"""WAV（PCM 16bit）と numpy の float32 配列の相互変換。サンプリングレートの変換はしない（音声認識のセッションで扱う）。"""

from __future__ import annotations

import io
import wave

import numpy as np


def wav_to_float32(data: bytes) -> tuple[np.ndarray, int]:
    """WAV のバイト列 → (-1.0〜1.0 の float32 モノラル配列, サンプリングレート)。PCM 16bit 以外は ValueError。"""
    with wave.open(io.BytesIO(data)) as wf:
        if wf.getsampwidth() != 2:
            raise ValueError(f"PCM 16bit の WAV だけを受け付けます（sampwidth={wf.getsampwidth()}）")
        frames = wf.readframes(wf.getnframes())
        channels, rate = wf.getnchannels(), wf.getframerate()
    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, rate


def pcm16_to_float32(pcm: bytes) -> np.ndarray:
    """ヘッダなしの PCM 16bit リトルエンディアン（WebSocket で届く形）→ float32 配列。"""
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def float32_to_wav(audio: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()
