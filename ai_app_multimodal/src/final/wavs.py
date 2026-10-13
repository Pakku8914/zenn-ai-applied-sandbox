"""WAV の連結（セッション9の wavs.py から join_wavs だけを写したもの）。"""

from __future__ import annotations

import io
import wave


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
