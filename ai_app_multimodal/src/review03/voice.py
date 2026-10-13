"""WS /ws/voice の1本の接続を受け持つ VoiceSession と、アプリの lifespan（セッション11の session.py・app.py の写し）。

中身はセッション11の本文と同じ。部品（VAD・文の組み立て・状態機械・再生の見積もり・会話履歴）は kit.py から使う。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing, asynccontextmanager
from typing import Any

import anthropic
import anyio
import httpx2
from anthropic import AsyncAnthropic
from fastapi import FastAPI, WebSocket
from ulid import ULID

from kondate import stt
from kondate.audio import pcm16_to_float32
from kondate.llm import AnthropicProvider, ChatRequest, Done, TextDelta
from kondate.settings import get_settings
from kondate.tts import Voicevox
from kondate.usage import UsageLog
from src.review03.kit import (
    FRAME_MS, INTERRUPTED_NOTE, SAMPLE_RATE, Conversation, PlaybackEstimate, SentenceBuffer, TurnMachine, TurnState,
    TurnTimes, UtteranceDetector,
)

settings = get_settings()
UPLINK_BYTES = SAMPLE_RATE * 20 // 1000 * 2      # 20ms の PCM 16bit ＝ 640 バイト
OUTPUT_RATE = 24000                               # 再生用（セッション9と同じ）
POLICY_VIOLATION = 1008
BARGE_IN_MS = 300                                 # 返答中は、1つの発話の声ありが 300ms に達したら割り込みとみなす
SYSTEM = ("あなたは献立相談AIです。返答は音声で読み上げるので、短い文で答えてください。"
          f"あなたの発言の最後に「{INTERRUPTED_NOTE}」とあるときは、その前の文までしかユーザーに伝わっていません。")
MSG_START = '最初に {"type":"start","sample_rate":16000} を送ってください'
MSG_FRAME = f"音声は 20ms（{UPLINK_BYTES} バイト）ずつ送ってください"
MSG_CONTROL = "テキストで送れるのは start と stop だけです"
MSG_UPSTREAM = "返答の生成に失敗しました。時間をおいて試してください"
MSG_TTS = "音声合成エンジンに接続できませんでした"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = AsyncAnthropic()
    app.state.llm = AnthropicProvider(client)
    app.state.voicevox = Voicevox()
    app.state.usage = UsageLog()
    app.state.stt_limiter = anyio.CapacityLimiter(1)
    app.state.transcriber = stt.transcribe
    yield
    await app.state.voicevox.aclose()
    await client.close()


class TurnFailed(Exception):
    """ターンを続けられない理由。上流の生のエラー文は持たせず、種別と日本語の固定文だけにする。"""

    def __init__(self, type_: str, message: str) -> None:
        super().__init__(message)
        self.type, self.message = type_, message


def parse_control(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class VoiceSession:
    def __init__(self, ws: WebSocket, state: Any, user_id: str = "u001",
                 detector: UtteranceDetector | None = None, *,
                 clock: Callable[[], float] = time.perf_counter, barge_in_ms: int = BARGE_IN_MS) -> None:
        self.ws, self.state, self.user_id = ws, state, user_id
        self.request_id = f"req_{ULID()}"
        self.detector = detector or UtteranceDetector()
        self.clock = clock
        self.barge_in_frames = barge_in_ms // FRAME_MS
        self.machine = TurnMachine()
        self.history = Conversation()
        self.playback = PlaybackEstimate()
        self.turn: asyncio.Task | None = None
        self.can_interrupt = False
        self.ignored = 0
        self.last_voice_at = 0.0
        self._send_lock = asyncio.Lock()

    # ---- 送信 ----
    async def send(self, payload: dict) -> None:
        async with self._send_lock:
            await self.ws.send_json(payload)

    async def send_audio(self, index: int, text: str, wav: bytes) -> None:
        async with self._send_lock:
            await self.ws.send_json({"type": "audio", "index": index, "text": text,
                                     "sample_rate": OUTPUT_RATE, "bytes": len(wav)})
            await self.ws.send_bytes(wav)

    async def send_error(self, type_: str, message: str) -> None:
        await self.send({"type": "error",
                         "error": {"type": type_, "message": message, "request_id": self.request_id}})

    async def reject(self, message: str) -> None:
        await self.send_error("invalid_request", message)
        await self.ws.close(code=POLICY_VIOLATION)

    # ---- 受信ループ ----
    async def run(self) -> None:
        try:
            first = await self.ws.receive()
            if first["type"] == "websocket.disconnect":
                return
            start = parse_control(first.get("text") or "")
            if not start or start.get("type") != "start" or start.get("sample_rate") != SAMPLE_RATE:
                await self.reject(MSG_START)
                return
            await self.send({"type": "ready", "credit": settings.voicevox_credit})
            while True:
                msg = await self.ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("bytes") is not None:
                    keep = await self.on_audio(msg["bytes"])
                else:
                    keep = await self.on_control(parse_control(msg.get("text") or ""))
                if not keep:
                    return
        finally:
            if self.turn is not None and not self.turn.done():
                self.turn.cancel()

    async def on_control(self, data: dict | None) -> bool:
        if data is not None and data.get("type") == "stop":
            if self.turn is not None:
                await self.turn
            await self.ws.close(code=1000)
            return False
        await self.reject(MSG_CONTROL)
        return False

    async def on_audio(self, data: bytes) -> bool:
        """20ms の PCM。どの状態でも VAD に通す。"""
        if len(data) != UPLINK_BYTES:
            await self.reject(MSG_FRAME)
            return False
        self.refresh_state(self.clock())
        before = self.detector.last_voiced_frame
        events = self.detector.push(data)
        now = self.clock()
        if self.detector.last_voiced_frame != before:
            self.last_voice_at = now
        for ev in events:
            if self.machine.state == TurnState.LISTENING:
                await self.send({"type": "vad", "state": ev.kind})
                if ev.kind == "speech_end":
                    self.start_turn(ev.audio, TurnTimes(last_voice=self.last_voice_at, speech_end=now))
                    break
            elif ev.kind == "speech_end":
                self.ignored += 1
        if self.should_barge_in():
            await self.barge_in()
        return True

    # ---- 状態 ----
    def refresh_state(self, now: float) -> None:
        if self.machine.state == TurnState.SPEAKING and self.turn is None and self.playback.finished(now):
            self.history.add_assistant(self.playback.heard(now), interrupted=False)
            self.machine.to(TurnState.LISTENING, "playback_done")
            self.drop_unconfirmed_speech()

    def drop_unconfirmed_speech(self) -> None:
        if self.detector.in_speech:
            self.detector.reset()

    def should_barge_in(self) -> bool:
        state = self.machine.state
        if state == TurnState.LISTENING or not self.detector.in_speech:
            return False
        if state == TurnState.THINKING and not self.can_interrupt:
            return False
        return self.detector.voiced_frames >= self.barge_in_frames

    async def barge_in(self) -> None:
        task = self.turn
        if task is not None:
            async with self._send_lock:
                task.cancel()
            await asyncio.wait({task})
        now = self.clock()
        if self.machine.state == TurnState.SPEAKING:
            index = self.playback.heard_count(now)
            self.history.add_assistant(self.playback.heard(now), interrupted=True)
        else:
            index = 0
        self.machine.to(TurnState.LISTENING, "barge_in")
        await self.send({"type": "vad", "state": "speech_start"})
        await self.send({"type": "interrupted", "index": index})

    # ---- ターン ----
    def start_turn(self, pcm: bytes, times: TurnTimes) -> None:
        self.playback = PlaybackEstimate()
        self.can_interrupt = False
        self.machine.to(TurnState.THINKING, "speech_end")
        self.turn = asyncio.create_task(self.run_turn(pcm, times))

    async def run_turn(self, pcm: bytes, t: TurnTimes) -> None:
        try:
            text = await self.transcribe(pcm)
            t.transcript = self.clock()
            await self.send({"type": "transcript", "text": text})
            if text:
                self.history.add_user(text)
                self.can_interrupt = True
                await self.reply(t)
            await self.send({"type": "turn_end", "latency_ms": t.latency_ms()})
        except TurnFailed as e:
            await self.send_error(e.type, e.message)
        finally:
            self.turn = None
        if self.machine.state == TurnState.THINKING:
            self.machine.to(TurnState.LISTENING, "no_reply")
            self.drop_unconfirmed_speech()

    async def transcribe(self, pcm: bytes) -> str:
        res = await anyio.to_thread.run_sync(
            self.state.transcriber, pcm16_to_float32(pcm), SAMPLE_RATE,
            limiter=self.state.stt_limiter,
        )
        self.state.usage.add(self.user_id, "stt", f"whisper:{settings.whisper_model}",
                             audio_seconds=round(res.audio_seconds, 3),
                             processing_seconds=round(res.processing_seconds, 3), request_id=self.request_id)
        return res.text.strip()

    async def reply(self, t: TurnTimes) -> None:
        sentences: asyncio.Queue[str | None] = asyncio.Queue()

        async def think() -> None:
            buf = SentenceBuffer()
            req = ChatRequest(messages=self.history.snapshot(), system=SYSTEM,
                              max_tokens=settings.llm_max_tokens)
            try:
                async with aclosing(self.state.llm.stream(req)) as events:
                    async for ev in events:
                        if isinstance(ev, TextDelta):
                            await self.send({"type": "reply_delta", "text": ev.text})
                            for s in buf.feed(ev.text):
                                t.sentence_ready(self.clock())
                                sentences.put_nowait(s)
                        elif isinstance(ev, Done):
                            self.state.usage.add(self.user_id, "llm", settings.llm_model,
                                                 input_tokens=ev.usage.input_tokens,
                                                 output_tokens=ev.usage.output_tokens, request_id=self.request_id)
            except (anthropic.APIError, httpx2.HTTPError):
                raise TurnFailed("upstream_unavailable", MSG_UPSTREAM) from None
            for s in buf.flush():
                t.sentence_ready(self.clock())
                sentences.put_nowait(s)
            sentences.put_nowait(None)

        async def speak() -> None:
            vv = self.state.voicevox
            index, audio_s, proc_s = 0, 0.0, 0.0
            try:
                await vv.ensure_user_dict()
                while (sentence := await sentences.get()) is not None:
                    r = await vv.synthesize(sentence, sample_rate=OUTPUT_RATE)
                    if index == 0:
                        t.tts_first = self.clock()
                    await self.send_audio(index, sentence, r.wav)
                    sent_at = self.clock()
                    self.playback.add(sentence, r.audio_seconds, sent_at)
                    if index == 0:
                        t.first_audio = sent_at
                        self.machine.to(TurnState.SPEAKING, "first_audio")
                    index += 1
                    audio_s += r.audio_seconds
                    proc_s += r.processing_seconds
            except httpx2.HTTPError:
                raise TurnFailed("tts_unavailable", MSG_TTS) from None
            finally:
                if index:                            # 取り消されたときも、合成して送った分は利用量に残す
                    self.state.usage.add(self.user_id, "tts", f"voicevox:{vv.speaker}",
                                         audio_seconds=round(audio_s, 3), processing_seconds=round(proc_s, 3),
                                         request_id=self.request_id)

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(think())
                tg.create_task(speak())
        except ExceptionGroup as group:
            failed = [e for e in group.exceptions if isinstance(e, TurnFailed)]
            if not failed:
                raise
            raise failed[0] from None
