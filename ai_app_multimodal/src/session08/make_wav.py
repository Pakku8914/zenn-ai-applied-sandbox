"""検証用の WAV を VOICEVOX で作って out/s08/ に書く（録音は使わない）。

    docker compose exec api python -m src.session08.make_wav
    docker compose exec api python -m src.session08.make_wav "タイマーを5分にセットして。" --rate 16000 --out out/s08/timer.wav
"""

from __future__ import annotations

import argparse
import asyncio
import io
import wave
from pathlib import Path

from kondate.tts import Voicevox
from src.session08.phrases import LOOPBACK_TEXT


async def make(text: str, rate: int) -> bytes:
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()
        return (await vv.synthesize(text, sample_rate=rate)).wav
    finally:
        await vv.aclose()


def main() -> int:
    p = argparse.ArgumentParser(description="VOICEVOX で検証用の WAV を作る")
    p.add_argument("text", nargs="?", default=LOOPBACK_TEXT)
    p.add_argument("--rate", type=int, default=24000, help="サンプリングレート（VOICEVOX の標準は 24000）")
    p.add_argument("--out", default="out/s08/loopback24k.wav")
    a = p.parse_args()

    wav = asyncio.run(make(a.text, a.rate))
    path = Path(a.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav)
    with wave.open(io.BytesIO(wav)) as wf:
        seconds = wf.getnframes() / wf.getframerate()
    print(f"{path}（{seconds:.2f} 秒・{a.rate}Hz・モノラル・PCM 16bit）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
