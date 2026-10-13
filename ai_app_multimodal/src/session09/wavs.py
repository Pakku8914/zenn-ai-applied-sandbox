"""WAV の諸元の読み取りと連結（標準ライブラリの wave だけを使う）。"""

from __future__ import annotations

import io
import wave


def wav_info(wav: bytes) -> tuple[int, int, int, int]:
    """(サンプリングレート, チャンネル数, 1サンプルのバイト数, 1チャンネルあたりのサンプル数)。"""
    with wave.open(io.BytesIO(wav)) as wf:
        return wf.getframerate(), wf.getnchannels(), wf.getsampwidth(), wf.getnframes()


def wav_seconds(wav: bytes) -> float:
    rate, _, _, frames = wav_info(wav)
    return frames / rate


def join_wavs(wavs: list[bytes]) -> bytes:
    """同じ形式（レート・チャンネル・ビット深度）の WAV を順につなぎ、1つの WAV にする。形式が違えば ValueError。"""
    if not wavs:
        raise ValueError("つなぐ WAV がありません")
    params, frames = None, []
    for wav in wavs:
        with wave.open(io.BytesIO(wav)) as wf:
            p = (wf.getframerate(), wf.getnchannels(), wf.getsampwidth())
            if params is None:
                params = p
            elif p != params:
                raise ValueError(f"形式が違う WAV はつなげません: {params} と {p}")
            frames.append(wf.readframes(wf.getnframes()))
    rate, channels, width = params
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(b"".join(frames))
    return buf.getvalue()
