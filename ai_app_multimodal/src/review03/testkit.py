"""音声対話を時間に頼らずに確かめる小道具（セッション11の testkit.py・talk.py から写した）。

時計・声の判定・音声認識・LLM・音声合成を、決まったふるまいをする偽物に差し替える。
"""

from __future__ import annotations

import asyncio
import io
import json
import wave
from collections.abc import Iterator
from contextlib import contextmanager

import numpy as np
from fastapi import FastAPI, WebSocket

from kondate import stt
from kondate.audio import float32_to_wav
from kondate.llm import ChatRequest, Done, TextDelta, Usage
from kondate.tts import TtsResult
from src.review03.kit import FRAME_BYTES, FRAME_MS, UtteranceDetector
from src.review03.voice import VoiceSession, lifespan

RATE = 16000
CHUNK = 640                                   # 20ms × 16kHz × 2 バイト
START = json.dumps({"type": "start", "sample_rate": RATE})
STOP = json.dumps({"type": "stop"})
VOICED, SILENT = b"\x01" * FRAME_BYTES, bytes(FRAME_BYTES)    # 偽の判定で「声あり」「声なし」になる 30ms


def pattern(*parts: tuple[bool, int]) -> bytes:
    """(声ありか, ミリ秒) の並びを PCM にする（30ms 単位。端数は切り捨て）。"""
    return b"".join((VOICED if voiced else SILENT) * (ms // FRAME_MS) for voiced, ms in parts)


def fake_detector() -> UtteranceDetector:
    """先頭のバイトが 1 のフレームを「声あり」とする検出器（webrtcvad を使わずに規則だけを確かめる）。"""
    return UtteranceDetector(is_speech=lambda frame: frame[0] == 1)


def chunks(pcm: bytes) -> list[bytes]:
    """PCM を 20ms（640 バイト）ずつに切る。最後の半端はゼロで埋める。"""
    pcm += bytes(-len(pcm) % CHUNK)
    return [pcm[i:i + CHUNK] for i in range(0, len(pcm), CHUNK)]


async def send_frames(conn, frames: list[bytes]) -> None:
    for frame in frames:
        await conn.send_bytes(frame)


async def receive_until(conn, log: list, stop_types: tuple[str, ...] = ("turn_end", "error"),
                        timeout: float = 60) -> None:
    """stop_types のどれかが届くか、接続が閉じるまで受け取り、log に足す（テキストは JSON にする）。"""
    async with asyncio.timeout(timeout):
        while (m := await conn.receive()) is not None:
            log.append(json.loads(m) if isinstance(m, str) else m)
            if isinstance(log[-1], dict) and log[-1]["type"] in stop_types:
                return


async def receive_until_audio(conn, log: list, index: int, timeout: float = 60) -> None:
    """audio {index} とその WAV を受け取るまで受け取る。"""
    async with asyncio.timeout(timeout):
        while (m := await conn.receive()) is not None:
            log.append(json.loads(m) if isinstance(m, str) else m)
            if (isinstance(log[-1], bytes) and len(log) >= 2 and isinstance(log[-2], dict)
                    and log[-2]["type"] == "audio" and log[-2]["index"] == index):
                return


class ManualClock:
    """検証が動かすまで止まっている時計。"""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class FixedTranscriber:
    """音声認識の代わりに、決まった文を順に返す（使い切ったら最後の文をくり返す）。"""

    def __init__(self, *texts: str) -> None:
        self.texts, self.calls = list(texts), 0

    def __call__(self, audio, rate: int) -> stt.SttResult:
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return stt.SttResult(text, len(audio) / rate, 0.0)


class ScriptedProvider:
    """呼ばれるたびに、決めた文を 6 文字ずつ流す LLM の代わり。hold_at を指定すると、その文字数まで流したあと
    続きを出さずに待ち続ける（遅い LLM の代わり）。最後まで流したか・途中で閉じられたかを数える。"""

    name = "scripted"

    def __init__(self, scripts: list[tuple[str, int | None]]) -> None:
        self.scripts = list(scripts)
        self.requests: list[ChatRequest] = []
        self.completed = 0
        self.closed_early = 0

    async def complete(self, req: ChatRequest):
        raise NotImplementedError

    async def stream(self, req: ChatRequest):
        self.requests.append(req)
        text, hold_at = self.scripts.pop(0)
        end = len(text) if hold_at is None else hold_at
        try:
            for i in range(0, end, 6):
                yield TextDelta(text[i:min(i + 6, end)])
            if hold_at is not None:
                await asyncio.Event().wait()
            yield Done("end_turn", Usage(1, 1))
            self.completed += 1
        except (asyncio.CancelledError, GeneratorExit):
            self.closed_early += 1
            raise


class FakeVoicevox:
    """1 文字 0.125 秒の無音 WAV を返す合成の代わり（合成を待たずに、状態と見積もりだけを確かめる）。"""

    speaker = 3

    async def ensure_user_dict(self) -> int:
        return 0

    async def synthesize(self, text: str, *, sample_rate: int = 16000) -> TtsResult:
        n = round(len(text) * 0.125 * sample_rate)
        return TtsResult(float32_to_wav(np.zeros(n, dtype=np.float32), sample_rate), "", n / sample_rate, 0.0)


@contextmanager
def swapped(state, **values) -> Iterator[None]:
    """app.state の項目を一時的に差し替え、終わったら元に戻す。"""
    saved = {k: getattr(state, k) for k in values}
    for k, v in values.items():
        setattr(state, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(state, k, v)


def probe_app(**kwargs) -> tuple[FastAPI, list[VoiceSession]]:
    """本文の app と同じ lifespan で、作ったセッションを外から見られるアプリ。"""
    sessions: list[VoiceSession] = []
    probe = FastAPI(lifespan=lifespan)

    @probe.websocket("/ws/voice")
    async def voice(ws: WebSocket) -> None:
        await ws.accept()
        session = VoiceSession(ws, ws.app.state, **kwargs)
        sessions.append(session)
        await session.run()

    return probe, sessions


def labels(log: list) -> list[str]:
    """reply_delta とバイナリを除いたメッセージを、"vad:speech_start"・"audio:1"・"interrupted:1" のような短い形にする。"""
    out = []
    for m in log:
        if not isinstance(m, dict) or m["type"] == "reply_delta":
            continue
        if m["type"] == "vad":
            out.append(f"vad:{m['state']}")
        elif m["type"] in ("audio", "interrupted"):
            out.append(f"{m['type']}:{m['index']}")
        else:
            out.append(m["type"])
    return out


def wav_seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as wf:
        return wf.getnframes() / wf.getframerate()
