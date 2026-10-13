"""起動中の api に、ネットワーク越しの WebSocket でつなぎ、合成した発話を 20ms ずつ送る。

    APP_MODULE=src.session10.app:app docker compose up -d --wait api   # ホストで（PowerShell は本文を参照）
    docker compose exec api python -m src.session10.voice_client

返事の音声は out/s10/reply_NN.wav に保存する（VOICEVOX の合成音。マイクの音ではない）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from src.session10.talk import converse, speech_pcm, utterance

URL = "ws://127.0.0.1:8000/ws/voice"          # api コンテナの中から見たアドレス（ホストからは 8720 番）
OUT = Path("out/s10")


class NetConn:
    """websockets の接続を、talk.converse が使う形（send_text・send_bytes・receive）に合わせる。"""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.close_code: int | None = None

    async def send_text(self, text: str) -> None:
        await self.ws.send(text)

    async def send_bytes(self, data: bytes) -> None:
        await self.ws.send(data)

    async def receive(self) -> str | bytes | None:
        try:
            return await self.ws.recv()
        except ConnectionClosed as e:
            self.close_code = e.rcvd.code if e.rcvd else None
            return None


async def main_async(text: str) -> int:
    pcm = await speech_pcm(text)
    async with connect(URL, max_size=4 * 1024 * 1024) as ws:
        conn = NetConn(ws)
        log = await converse(conn, utterance(pcm), realtime=True)
    OUT.mkdir(parents=True, exist_ok=True)
    deltas = 0
    for i, m in enumerate(log):
        if isinstance(m, bytes):
            continue
        if m["type"] == "reply_delta":
            deltas += 1
            continue
        if deltas:
            print(f"reply_delta ×{deltas}")
            deltas = 0
        if m["type"] == "audio":
            path = OUT / f"reply_{m['index']:02d}.wav"
            path.write_bytes(log[i + 1])
            print(f"audio {m['index']} {m['sample_rate']}Hz {m['bytes']}バイト「{m['text'][:12]}…」→ {path}")
        else:
            print(m)
    print(f"close {conn.close_code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(sys.argv[1] if len(sys.argv) > 1 else "鶏むね肉とキャベツで20分で作れる料理は？")))
