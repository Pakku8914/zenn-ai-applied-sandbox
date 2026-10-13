"""問題1：audio_query を要約し、読み・拍・間・おおよその長さを数える。

    docker compose exec api python -m src.session09.solutions.q1_summary "鶏むね肉とキャベツで20分で作れる料理は？"
"""

from __future__ import annotations

import asyncio
import sys

from kondate.tts import Voicevox
from src.session09 import vvapi
from src.session09.wavs import wav_seconds


def summarize_query(query: dict) -> dict:
    phrases = query["accent_phrases"]
    moras = [m for ap in phrases for m in ap["moras"]]
    pauses = [ap["pause_mora"] for ap in phrases if ap.get("pause_mora")]
    voiced = sum((m["consonant_length"] or 0.0) + m["vowel_length"] for m in moras)
    silent = sum(p["vowel_length"] for p in pauses)
    edges = query["prePhonemeLength"] + query["postPhonemeLength"]
    return {
        "reading": vvapi.plain_kana(query["kana"]),
        "accent_phrases": len(phrases),
        "moras": len(moras),
        "devoiced": sum(m["vowel"] in {"A", "I", "U", "E", "O"} for m in moras),   # 無声化した母音は大文字
        "pauses": len(pauses),
        "interrogative": bool(phrases and phrases[-1]["is_interrogative"]),
        "seconds_estimate": round(edges + voiced + silent, 3),      # speedScale 1.0 のときの目安
    }


async def main_async(text: str) -> int:
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()
        async with vvapi.client() as c:
            query = await vvapi.audio_query(c, text)
            query["outputSamplingRate"] = 24000
            wav = await vvapi.synthesis(c, query)
    finally:
        await vv.aclose()
    for key, value in summarize_query(query).items():
        print(f"{key}: {value}")
    print(f"WAV の長さ: {wav_seconds(wav):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(sys.argv[1] if len(sys.argv) > 1 else "鶏むね肉とキャベツで20分で作れる料理は？")))
