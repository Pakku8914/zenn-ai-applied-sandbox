"""問題7：最初の文だけを読点で短くして、最初の音を早める。

    docker compose exec api python -m src.session09.solutions.q7_first_short
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from kondate.tts import Voicevox
from src.session09.first_audio import fetch_reply
from src.session09.sentences import split_sentences

OUT = Path("out/s09")


def shorten_first(sentences: list[str], max_chars: int = 20) -> list[str]:
    """1文目が max_chars 文字より長ければ、max_chars 文字以内で最後の「、」の直後で2つに分ける。2文目以降は触らない。"""
    if not sentences or len(sentences[0]) <= max_chars:
        return list(sentences)
    first = sentences[0]
    cut = first.rfind("、", 0, max_chars)
    if cut <= 0:                                       # 範囲内に読点がなければ分けない
        return list(sentences)
    return [first[: cut + 1], first[cut + 1 :], *sentences[1:]]


async def main_async() -> int:
    sentences = split_sentences(await fetch_reply())
    short = shorten_first(sentences)
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()
        await vv.synthesize("準備です。", sample_rate=24000)
        a = await vv.synthesize(sentences[0], sample_rate=24000)
        b = await vv.synthesize(short[0], sample_rate=24000)
    finally:
        await vv.aclose()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "first_before.wav").write_bytes(a.wav)
    (OUT / "first_after.wav").write_bytes(b.wav)
    print(f"分ける前の1文目: {sentences[0]}（音声 {a.audio_seconds:.2f}秒・合成 {a.processing_seconds:.2f}秒）")
    print(f"分けた後の1文目: {short[0]}（音声 {b.audio_seconds:.2f}秒・合成 {b.processing_seconds:.2f}秒）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
