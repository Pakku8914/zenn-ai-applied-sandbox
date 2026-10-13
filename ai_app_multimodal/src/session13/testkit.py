"""検証と練習問題で共通に使う小道具（セッション13）。

音声認識・LLM・音声合成・VAD を決まった答えを返すものに差し替え、時計を FixedClock にし、
生成物の置き場所を out/s13/ の下に変える。Whisper・VOICEVOX・mockllm は使わない（課金なし・決定的）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from kondate import stt
from kondate.clock import FixedClock
from kondate.llm import ChatResult, FakeProvider, Usage
from kondate.tts import TtsResult
from kondate.usage import UsageLog
from src.session13.asgi_ws import AsgiWebSocket
from src.session13.privacy import PersonalStore
from src.session13.vad import FRAME_BYTES, UtteranceDetector

TEXT = "鶏むね肉とキャベツで20分で作れる料理は？"       # 検証用の発話（LOOPBACK_TEXT と同じ文）
REPLY = "鶏むね肉とキャベツの塩炒めはいかがですか。"
VOICED, SILENT = b"\x01" * FRAME_BYTES, bytes(FRAME_BYTES)   # 30ms ぶん。先頭が 1 なら「声あり」と見なす
STOP = json.dumps({"type": "stop"})
CHUNK = 640                                                 # 20ms の上り


def chunks(pcm: bytes) -> list[bytes]:
    pcm += bytes(-len(pcm) % CHUNK)
    return [pcm[i:i + CHUNK] for i in range(0, len(pcm), CHUNK)]


def utterance_frames() -> list[bytes]:
    """無音 0.3 秒 → 声 0.9 秒 → 無音 0.75 秒。VAD が切り出す1発話は 1.8 秒（57,600 バイト）になる。"""
    return chunks(SILENT * 10 + VOICED * 30 + SILENT * 25)


def fake_detector() -> UtteranceDetector:
    return UtteranceDetector(is_speech=lambda frame: frame[0] == 1)


class FixedTranscriber:
    """音声認識の代わりに、決まった文を返す。"""

    def __init__(self, text: str) -> None:
        self.text = text

    def __call__(self, audio, rate: int) -> stt.SttResult:
        return stt.SttResult(self.text, len(audio) / rate, 0.0)


class FakeVoice:
    """VOICEVOX の代わり。中身のない WAV を返す。"""

    speaker = 3

    async def ensure_user_dict(self) -> int:
        return 0

    async def synthesize(self, text: str, *, sample_rate: int = 16000) -> TtsResult:
        return TtsResult(b"RIFF-fake", "", 0.1, 0.0)

    async def aclose(self) -> None:
        return None


class Collect(logging.Handler):
    """書式を通したログの行を集める（画面に出さずに、中身を確かめるため）。"""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def count_files(directory: Path) -> int:
    return sum(1 for p in directory.iterdir() if p.is_file()) if directory.is_dir() else 0


@contextmanager
def swapped(state: Any, **values: Any) -> Iterator[None]:
    """app.state の項目を一時的に差し替え、終わったら元に戻す。"""
    saved = {k: getattr(state, k) for k in values}
    for k, v in values.items():
        setattr(state, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(state, k, v)


@contextmanager
def sandboxed(app: Any, out: Path, clock: FixedClock | None = None) -> Iterator[Any]:
    """lifespan の中で使う。台帳・利用記録・置き場所・音声の部品を、検証用の新しいものに差し替える。"""
    shutil.rmtree(out, ignore_errors=True)
    clock = clock or FixedClock()
    replies = [ChatResult(REPLY, [], "end_turn", Usage(1, 1)) for _ in range(10)]
    with swapped(app.state, clock=clock, data=PersonalStore(clock), usage=UsageLog(clock),
                 upload_dir=out / "uploads", voice_dir=out / "voice",
                 transcriber=FixedTranscriber(TEXT), llm=FakeProvider(replies),
                 voicevox=FakeVoice(), make_detector=fake_detector):
        yield app.state


async def receive_until(ws: AsgiWebSocket, log: list, stop_types: tuple[str, ...] = ("turn_end", "error"),
                        timeout: float = 30) -> None:
    async with asyncio.timeout(timeout):
        while (m := await ws.receive()) is not None:
            log.append(json.loads(m) if isinstance(m, str) else m)
            if isinstance(log[-1], dict) and log[-1]["type"] in stop_types:
                return


async def voice_turn(app: Any, start: dict, user_id: str = "u001") -> tuple[list, int | None]:
    """start → 1発話 → turn_end（か error）→ stop → 閉じるまで。受け取ったメッセージと close コードを返す。"""
    log: list = []
    async with AsgiWebSocket(app, headers={"x-user-id": user_id}) as ws:
        await ws.send_text(json.dumps(start))
        for frame in utterance_frames():
            await ws.send_bytes(frame)
        await receive_until(ws, log)
        await ws.send_text(STOP)
        await receive_until(ws, log, stop_types=())
    return log, ws.close_code
