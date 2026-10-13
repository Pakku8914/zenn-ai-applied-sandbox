"""問題1：WAV の諸元を読み、16kHz・モノラルにしたときの大きさを見積もる。

    docker compose exec api python -m src.session08.solutions.q1_describe_wav out/s08/loopback24k.wav
"""

from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

TARGET_RATE = 16000


def describe_wav(raw: bytes) -> dict:
    with wave.open(io.BytesIO(raw)) as wf:
        rate, channels, width, frames = wf.getframerate(), wf.getnchannels(), wf.getsampwidth(), wf.getnframes()
    frames_16k = round(frames * TARGET_RATE / rate)       # to_16k_mono と同じ数え方
    return {
        "sample_rate": rate,
        "channels": channels,
        "bits": width * 8,
        "frames": frames,
        "seconds": round(frames / rate, 3),
        "file_bytes": len(raw),
        "bytes_per_second": rate * channels * width,
        "pcm_bytes_16k_mono": frames_16k * 2,                # 16bit = 2 バイト × 1 チャンネル
    }


def main(argv: list[str]) -> int:
    for name in argv:
        info = describe_wav(Path(name).read_bytes())
        print(name)
        for key, value in info.items():
            print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
