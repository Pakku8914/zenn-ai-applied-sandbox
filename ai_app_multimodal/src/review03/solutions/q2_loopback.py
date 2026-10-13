"""問題2：読み上げた声（24kHz・セッション9）を、音声認識の受付（セッション8）に通して文字に戻す（閉ループ検査）。

    docker compose exec api python -m src.review03.solutions.q2_loopback
"""

from __future__ import annotations

import asyncio
import hashlib

import anyio

from kondate import stt
from kondate.audio import wav_to_float32
from kondate.metrics import cer
from kondate.tts import Voicevox
from src.review03.kit import LOOPBACK_TEXT, TARGET_RATE, cer_relaxed, decode_wav, wav_info

OUTPUT_RATE = 24000                    # /api/voice/speak が返すのと同じ再生用のレート
SENTENCES = (LOOPBACK_TEXT, "冷蔵庫に卵と牛乳とにんじんがあります。")
CER_LIMIT = 0.10                       # 表記ゆれを吸収したあとの CER の上限


def yes(ok: bool) -> str:
    return "はい" if ok else "いいえ"


async def loopback(vv: Voicevox, limiter: anyio.CapacityLimiter, text: str) -> str:
    first = await vv.synthesize(text, sample_rate=OUTPUT_RATE)
    again = await vv.synthesize(text, sample_rate=OUTPUT_RATE)
    same = hashlib.sha256(first.wav).digest() == hashlib.sha256(again.wav).digest()
    rate, channels, width, frames = wav_info(first.wav)

    audio16 = await anyio.to_thread.run_sync(decode_wav, first.wav)      # 受付と 16kHz への変換（セッション8）
    resampled = len(audio16) == round(frames * TARGET_RATE / rate)
    stretch = (frames / TARGET_RATE) / (frames / rate)                    # 16kHz と偽ったら何倍の長さになるか

    res = await anyio.to_thread.run_sync(stt.transcribe, audio16, TARGET_RATE, limiter=limiter)
    strict, relaxed = cer(text, res.text), cer_relaxed(text, res.text)
    return (f"{text} → {rate}Hz・{channels}ch・{width * 8}bit・SHA256 {'一致' if same else '不一致'}"
            f" → 16kHz のサンプル数 {'一致' if resampled else '不一致'}・16kHz と偽ると {stretch:.2f} 倍"
            f" → ゆれ吸収 CER ≤ {CER_LIMIT:.2f} {yes(relaxed <= CER_LIMIT)}・厳密 ≥ ゆれ吸収 {yes(strict >= relaxed)}")


async def run() -> None:
    limiter = anyio.CapacityLimiter(1)                 # 認識は同時に1件（セッション8）
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()                    # 「鶏むね肉」を「トリムネニク」と読ませる
        for text in SENTENCES:
            print(await loopback(vv, limiter, text))
        wav24 = (await vv.synthesize(SENTENCES[0], sample_rate=OUTPUT_RATE)).wav
    finally:
        await vv.aclose()
    audio24, rate = wav_to_float32(wav24)
    try:
        await anyio.to_thread.run_sync(stt.transcribe, audio24, rate, limiter=limiter)
        print("24kHz のまま渡すと: 認識できてしまった")
    except ValueError as e:
        print(f"24kHz のまま渡すと: ValueError「{e}」")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
