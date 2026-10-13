"""POST /api/voice/speak を呼び、WAV を out/s09/ に保存して、ヘッダと諸元を表示する。

    APP_MODULE=src.session09.app:app docker compose up -d --wait api   （ホスト側で切り替えておく）
    docker compose exec api python -m src.session09.speak_client "鶏むね肉を一口大に切ります。"
    docker compose exec api python -m src.session09.speak_client --reply      # kondate_chat の返答を丸ごと読む
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from urllib.parse import unquote

import httpx2

from kondate.settings import get_settings
from src.session09.first_audio import fetch_reply
from src.session09.wavs import wav_info

OUT = Path("out/s09")


async def speak(text: str, name: str) -> int:
    async with httpx2.AsyncClient(base_url=get_settings().api_base_url, timeout=120) as client:
        r = await client.post("/api/voice/speak", json={"text": text})
    print(f"status: {r.status_code}")
    if r.status_code != 200:
        print(r.json())
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_bytes(r.content)
    rate, channels, width, frames = wav_info(r.content)
    print(f"content-type: {r.headers['content-type']}")
    print(f"x-voice-credit: {r.headers['x-voice-credit']}")
    print(f"クレジット（デコード後）: {unquote(r.headers['x-voice-credit'])}")
    print(f"WAV: {rate}Hz・{channels}ch・{width * 8}bit・{frames / rate:.2f}秒 → {path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="POST /api/voice/speak を試す")
    p.add_argument("text", nargs="?", default="鶏むね肉を一口大に切ります。")
    p.add_argument("--reply", action="store_true", help="mockllm の献立相談の返答を読み上げる")
    a = p.parse_args()
    if a.reply:
        return asyncio.run(_reply())
    return asyncio.run(speak(a.text, "speak.wav"))


async def _reply() -> int:
    return await speak(await fetch_reply(), "reply.wav")


if __name__ == "__main__":
    raise SystemExit(main())
