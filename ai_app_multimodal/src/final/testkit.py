"""検証（verify_*.py）で使う小道具。アプリ本体からは使わない（セッション6・11・13・14の testkit の写しを集めたもの）。

- running() … 起動の前に時計・ウォームアップ・置き場所を差し替えてから lifespan を動かし、アプリに直接投げる
- 偽物：決まった文を返す音声認識・決まった文を流す LLM・無音の WAV を返す音声合成・先頭の1バイトで判定する VAD
- RecipeReaderFake … 送られてきた PDF を pypdf で読み、正しい JSON を返す（取り込みの中身を決定的に確かめる）
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import math
import shutil
import wave
from collections.abc import AsyncIterator, Iterator
from contextlib import aclosing, asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import httpx2
import numpy as np
from fastapi import FastAPI, WebSocket

from kondate import stt
from kondate.audio import float32_to_wav
from kondate.clock import Clock, SystemClock
from kondate.llm import ChatRequest, ChatResult, Done, TextDelta, Usage
from kondate.settings import get_settings
from kondate.tts import TtsResult
from src.final.app import app as final_app
from src.final.app import lifespan
from src.final.asgi_ws import AsgiWebSocket
from src.final.documents import extract_pages
from src.final.pages import parse_heading
from src.final.session import VoiceSession
from src.final.talk import STOP, chunks, receive_until
from src.final.vad import FRAME_BYTES, FRAME_MS, UtteranceDetector

S = get_settings()
TEXT = "鶏むね肉とキャベツで20分で作れる料理は？"   # LOOPBACK_TEXT と同じ文
VOICED, SILENT = b"\x01" * FRAME_BYTES, bytes(FRAME_BYTES)
NO_WARMUP: dict = {}
OUT = Path("out/final")


# ---------------------------------------------------------------- 起動

@asynccontextmanager
async def running(app: FastAPI = final_app, *, clock: Clock | None = None, out: Path | None = None,
                  warmers: dict | None = NO_WARMUP) -> AsyncIterator[httpx2.AsyncClient]:
    """起動の前に時計・ウォームアップ・置き場所を差し替え、lifespan を動かしてから httpx のクライアントを渡す。"""
    s = app.state
    saved = {k: getattr(s, k) for k in ("clock", "warmers", "upload_dir", "voice_dir")}
    s.clock, s.warmers = clock or SystemClock(), warmers
    if out is not None:
        shutil.rmtree(out, ignore_errors=True)
        s.upload_dir, s.voice_dir = out / "uploads", out / "voice"
    try:
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=180) as client:
                yield client
    finally:
        for k, v in saved.items():
            setattr(s, k, v)


@contextmanager
def swapped(state: Any, **values: Any) -> Iterator[None]:
    saved = {k: getattr(state, k) for k in values}
    for k, v in values.items():
        setattr(state, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(state, k, v)


async def mock(method: str, path: str) -> dict:
    async with httpx2.AsyncClient(base_url=S.mockllm_url, timeout=10) as c:
        r = await c.request(method, path)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------- 音声の偽物

def pattern(*parts: tuple[bool, int]) -> bytes:
    """(声ありか, ミリ秒) の並びを PCM にする（30ms 単位）。"""
    return b"".join((VOICED if voiced else SILENT) * (ms // FRAME_MS) for voiced, ms in parts)


def utterance_frames() -> list[bytes]:
    """無音 0.3 秒 → 声 0.9 秒 → 無音 0.75 秒。偽の VAD が切り出す1発話は 1.8 秒（57,600 バイト）。"""
    return chunks(pattern((False, 300), (True, 900), (False, 750)))


def fake_detector() -> UtteranceDetector:
    return UtteranceDetector(is_speech=lambda frame: frame[0] == 1)


class ManualClock:
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


class FakeVoicevox:
    """1 文字 0.125 秒の無音 WAV を返す音声合成の代わり。"""

    speaker = 3

    def __init__(self) -> None:
        self.calls = 0

    async def ensure_user_dict(self) -> int:
        return 0

    async def synthesize(self, text: str, *, sample_rate: int = 16000) -> TtsResult:
        self.calls += 1
        n = round(len(text) * 0.125 * sample_rate)
        return TtsResult(float32_to_wav(np.zeros(n, dtype=np.float32), sample_rate), "", n / sample_rate, 0.0)


class ScriptedProvider:
    """決めた文を 6 文字ずつ流す LLM の代わり。hold_at の文字数まで流したら、続きを出さずに待ち続ける。"""

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
    """本物の LLMProvider を包み、渡したリクエストを記録する。"""

    name = "observed"

    def __init__(self, inner) -> None:
        self.inner = inner
        self.requests: list[ChatRequest] = []

    async def complete(self, req: ChatRequest):
        self.requests.append(req)
        return await self.inner.complete(req)

    async def stream(self, req: ChatRequest):
        self.requests.append(req)
        async with aclosing(self.inner.stream(req)) as events:
            async for ev in events:
                yield ev


def probe_app(**session_kwargs) -> tuple[FastAPI, list[VoiceSession]]:
    """本番と同じ lifespan で、作ったセッションを外から見られるアプリ（時計を差し替えた割り込みの検証に使う）。"""
    sessions: list[VoiceSession] = []
    probe = FastAPI(lifespan=lifespan)
    probe.state.clock, probe.state.warmers = SystemClock(), NO_WARMUP
    probe.state.upload_dir, probe.state.voice_dir = OUT / "probe" / "uploads", OUT / "probe" / "voice"

    @probe.websocket("/ws/voice")
    async def voice(ws: WebSocket) -> None:
        await ws.accept()
        session = VoiceSession(ws, ws.app.state, **session_kwargs)
        sessions.append(session)
        await session.run()

    return probe, sessions


async def voice_turn(app: Any, start: dict, user_id: str = "u001") -> tuple[list, int | None]:
    """start → 1発話（偽の VAD 用）→ turn_end か error → stop → 閉じるまで。受け取ったものと close コードを返す。"""
    log: list = []
    async with AsgiWebSocket(app, headers={"x-user-id": user_id}) as ws:
        await ws.send_text(json.dumps(start))
        for frame in utterance_frames():
            await ws.send_bytes(frame)
        await receive_until(ws, log, timeout=60)
        await ws.send_text(STOP)
        await receive_until(ws, log, stop_types=(), timeout=60)
    return log, ws.close_code


def labels(log: list) -> list[str]:
    """reply_delta とバイナリを除き、"vad:speech_start"・"audio:1"・"interrupted:1" のような短い形にする。"""
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


# ---------------------------------------------------------------- ログ・取り込み

class Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


class RecipeReaderFake:
    """答えを知っている LLM の代わり（セッション6の fakes.py から、読み落としなどの仕掛けを除いたもの）。"""

    name = "recipe-reader-fake"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, req: ChatRequest) -> ChatResult:
        self.calls += 1
        texts = extract_pages(base64.b64decode(req.messages[0]["content"][0]["source"]["data"]))
        recipes = []
        for page, text in enumerate(texts, 1):
            h = parse_heading(text, page)
            if h is not None:
                recipes.append({"id": h.recipe_id, "name": h.name, "page": page,
                                "minutes": h.minutes, "servings": h.servings, "kcal": h.kcal})
        out = json.dumps({"recipes": recipes}, ensure_ascii=False)
        return ChatResult(out, [], "end_turn", Usage(len(texts) * 1600, math.ceil(len(out.encode("utf-8")) / 3)))

    async def stream(self, req: ChatRequest):
        raise NotImplementedError
        yield
