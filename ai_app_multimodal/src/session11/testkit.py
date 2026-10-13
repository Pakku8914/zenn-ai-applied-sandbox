"""検証（verify.py・verify_solutions.py）で使う小道具。アプリ本体からは使わない。

割り込みは「いつ話しかけたか」で結果が変わるので、時間に頼らずに決まった結果を出せるよう、
時計・声の判定・音声認識・LLM・音声合成を、決まったふるまいをする偽物に差し替えられるようにする。
"""

from __future__ import annotations

import asyncio
import io
import wave
from collections.abc import Iterator
from contextlib import aclosing, contextmanager

import numpy as np
from fastapi import FastAPI, WebSocket

from kondate import stt
from kondate.audio import float32_to_wav
from kondate.llm import ChatRequest, Done, TextDelta, Usage
from kondate.tts import TtsResult
from src.session11.app import lifespan
from src.session11.session import VoiceSession
from src.session11.vad import FRAME_BYTES, FRAME_MS, UtteranceDetector

VOICED, SILENT = b"\x01" * FRAME_BYTES, bytes(FRAME_BYTES)    # 偽の判定で「声あり」「声なし」になる 30ms


def pattern(*parts: tuple[bool, int]) -> bytes:
    """(声ありか, ミリ秒) の並びを PCM にする（30ms 単位。端数は切り捨て）。"""
    return b"".join((VOICED if voiced else SILENT) * (ms // FRAME_MS) for voiced, ms in parts)


def fake_detector() -> UtteranceDetector:
    """先頭のバイトが 1 のフレームを「声あり」とする検出器（webrtcvad を使わずに規則だけを確かめる）。"""
    return UtteranceDetector(is_speech=lambda frame: frame[0] == 1)


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


class Observed:
    """本物の LLMProvider を包み、リクエストと「最後まで流したか・途中で閉じられたか」を記録する。
    n 回目の呼び出しは inners[n]（足りなければ最後のもの）に渡す。"""

    name = "observed"

    def __init__(self, *inners) -> None:
        self.inners = inners
        self.requests: list[ChatRequest] = []
        self.completed = 0
        self.closed_early = 0

    async def complete(self, req: ChatRequest):
        raise NotImplementedError

    async def stream(self, req: ChatRequest):
        inner = self.inners[min(len(self.requests), len(self.inners) - 1)]
        self.requests.append(req)
        try:
            async with aclosing(inner.stream(req)) as events:
                async for ev in events:
                    yield ev
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


def probe_app(session_class: type[VoiceSession] = VoiceSession, **kwargs) -> tuple[FastAPI, list[VoiceSession]]:
    """本文の app と同じ lifespan で、作ったセッションを外から見られるアプリ（状態の記録や履歴を確かめるため）。"""
    sessions: list[VoiceSession] = []
    probe = FastAPI(lifespan=lifespan)

    @probe.websocket("/ws/voice")
    async def voice(ws: WebSocket) -> None:
        await ws.accept()
        session = session_class(ws, ws.app.state, **kwargs)
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
