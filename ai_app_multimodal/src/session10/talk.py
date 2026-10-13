"""音声対話のクライアント側の小道具（verify・計測・voice_client で共通に使う）。

マイクの代わりに、VOICEVOX で合成した発話を 16kHz の PCM にして 20ms（640 バイト）ずつ送る。
後ろに足す無音（ゼロの PCM）が、VAD にとっての「話し終わり」になる。
"""

from __future__ import annotations

import asyncio
import io
import json
import wave
from typing import Protocol

from kondate.tts import Voicevox

RATE = 16000
CHUNK = 640                                   # 20ms × 16kHz × 2 バイト
START = json.dumps({"type": "start", "sample_rate": RATE})
STOP = json.dumps({"type": "stop"})


class Conn(Protocol):
    """AsgiWebSocket（ASGI 直結）と、ネットワーク越しの接続に共通する形。"""

    async def send_text(self, text: str) -> None: ...
    async def send_bytes(self, data: bytes) -> None: ...
    async def receive(self) -> str | bytes | None: ...


async def speech_pcm(text: str) -> bytes:
    """VOICEVOX で文を 16kHz で読み上げ、WAV のヘッダを除いた PCM 16bit を返す。"""
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()
        wav = (await vv.synthesize(text, sample_rate=RATE)).wav
    finally:
        await vv.aclose()
    with wave.open(io.BytesIO(wav)) as wf:
        return wf.readframes(wf.getnframes())


def silence(seconds: float) -> bytes:
    return bytes(round(RATE * seconds) * 2)


def chunks(pcm: bytes) -> list[bytes]:
    """PCM を 20ms（640 バイト）ずつに切る。最後の半端はゼロで埋める。"""
    pcm += bytes(-len(pcm) % CHUNK)
    return [pcm[i:i + CHUNK] for i in range(0, len(pcm), CHUNK)]


def utterance(pcm: bytes, lead: float = 0.5, tail: float = 1.5) -> list[bytes]:
    """前に lead 秒・後ろに tail 秒の無音を足して、20ms ずつにする。"""
    return chunks(silence(lead) + pcm + silence(tail))


def kinds(log: list) -> list[str]:
    """受け取ったメッセージの種類の列（バイナリは "binary"）。"""
    return [m["type"] if isinstance(m, dict) else "binary" for m in log]


async def send_frames(conn: Conn, frames: list[bytes], *, realtime: bool = False) -> None:
    """音声を送る。realtime なら、マイクと同じく 20ms ごとに1つずつ送る。"""
    loop = asyncio.get_running_loop()
    began = loop.time()
    for i, frame in enumerate(frames):
        if realtime:
            await asyncio.sleep(max(0.0, began + i * 0.02 - loop.time()))   # 遅れが積み重ならないよう、予定の時刻に合わせる
        await conn.send_bytes(frame)


async def receive_until(conn: Conn, log: list, stop_types: tuple[str, ...] = ("turn_end", "error"),
                        timeout: float = 180) -> None:
    """stop_types のどれかが届くか、接続が閉じるまで受け取り、log に足す（テキストは JSON にする）。"""
    async with asyncio.timeout(timeout):
        while (m := await conn.receive()) is not None:
            log.append(json.loads(m) if isinstance(m, str) else m)
            if isinstance(log[-1], dict) and log[-1]["type"] in stop_types:
                return


async def converse(conn: Conn, frames: list[bytes], *, realtime: bool = False) -> list:
    """1ターンの会話：start → 音声 → turn_end（か error）まで受け取る → stop → 閉じるまで受け取る。"""
    log: list = []
    await conn.send_text(START)
    await asyncio.gather(send_frames(conn, frames, realtime=realtime), receive_until(conn, log))
    await conn.send_text(STOP)
    await receive_until(conn, log, stop_types=())
    return log
