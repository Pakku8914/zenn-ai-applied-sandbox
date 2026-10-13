"""WS /ws/voice の1本の接続を受け持つ（WebSocket の取り決めはセッション10・11と同じ）。

セッション11の VoiceSession（割り込み・ターン制御）をもとに、次の5つを足した（「# 最終」の印を付けた行）。
1. 同意（セッション13）：start の store_audio が JSON の true のときだけ1発話を WAV で保存する（7日）。ready で受け付けた値を返す
2. 入口（セッション14）：認識は stt_gate、合成は tts_gate を通す。あふれたら error {type: stt_busy / tts_busy}
3. 利用量（セッション14）：UsageBook に記録する（GET /api/usage に WebSocket の分も出る）
4. 手元の食材（最終）：写真・レシートから読み取った食材名を system に添える（mockllm の照合は最後の user 発言で決まる）
5. ログ（セッション13）：文字起こしは長さと SHA256 の先頭12桁だけを記録する
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
import wave
from collections.abc import Callable
from contextlib import aclosing
from pathlib import Path
from typing import Any

import anthropic
import anyio
import httpx2
from fastapi import WebSocket
from ulid import ULID

from kondate.audio import pcm16_to_float32
from kondate.llm import ChatRequest, Done, TextDelta
from kondate.settings import get_settings
from src.final.gate import Busy
from src.final.history import INTERRUPTED_NOTE, Conversation
from src.final.latency import TurnTimes
from src.final.logmask import sha12
from src.final.pantry import pantry_names, system_with_pantry
from src.final.playback import PlaybackEstimate
from src.final.sentence_buffer import SentenceBuffer
from src.final.turns import TurnMachine, TurnState
from src.final.vad import FRAME_MS, SAMPLE_RATE, UtteranceDetector

settings = get_settings()
log = logging.getLogger(__name__)
UPLINK_BYTES = SAMPLE_RATE * 20 // 1000 * 2      # 20ms の PCM 16bit ＝ 640 バイト
OUTPUT_RATE = 24000
POLICY_VIOLATION = 1008
BARGE_IN_MS = 300
SYSTEM = ("あなたは献立相談AIです。返答は音声で読み上げるので、短い文で答えてください。"
          f"あなたの発言の最後に「{INTERRUPTED_NOTE}」とあるときは、その前の文までしかユーザーに伝わっていません。")
MSG_START = '最初に {"type":"start","sample_rate":16000} を送ってください'
MSG_FRAME = f"音声は 20ms（{UPLINK_BYTES} バイト）ずつ送ってください"
MSG_CONTROL = "テキストで送れるのは start と stop だけです"
MSG_UPSTREAM = "返答の生成に失敗しました。時間をおいて試してください"
MSG_TTS = "音声合成エンジンに接続できませんでした"
MSG_STT_BUSY = "音声認識が混み合っています。少し待ってから試してください"
MSG_TTS_BUSY = "音声合成が混み合っています。少し待ってから試してください"


class TurnFailed(Exception):
    def __init__(self, type_: str, message: str) -> None:
        super().__init__(message)
        self.type, self.message = type_, message


def parse_control(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def wants_storage(start: dict) -> bool:
    """保存してよいのは、はっきり同意したとき（JSON の true）だけ（セッション13）。"""
    return start.get("store_audio") is True


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return out.getvalue()


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(data)


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
        self.store_audio = False                     # 最終：既定は「保存しない」（セッション13）
        self._send_lock = asyncio.Lock()

    # ---- 送信（セッション11と同じ）----
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
            self.store_audio = wants_storage(start)                                       # 最終
            log.info("voice_start", extra={"fields": {"user_id": self.user_id, "request_id": self.request_id,
                                                      "store_audio": self.store_audio}})
            await self.send({"type": "ready", "credit": settings.voicevox_credit,
                             "store_audio": self.store_audio})                            # 最終
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

    # ---- 状態（セッション11と同じ）----
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

    # ---- ターン：（同意があれば保存）→ 認識 → LLM → 文ごとの合成 ----
    def start_turn(self, pcm: bytes, times: TurnTimes) -> None:
        self.playback = PlaybackEstimate()
        self.can_interrupt = False
        self.machine.to(TurnState.THINKING, "speech_end")
        self.turn = asyncio.create_task(self.run_turn(pcm, times))

    async def run_turn(self, pcm: bytes, t: TurnTimes) -> None:
        try:
            if self.store_audio:                                                          # 最終
                await self.keep_audio(pcm)
            text = await self.transcribe(pcm)
            t.transcript = self.clock()
            log.info("transcript", extra={"fields": {"user_id": self.user_id, "request_id": self.request_id,
                                                     "chars": len(text), "sha12": sha12(text)}})   # 最終
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

    async def keep_audio(self, pcm: bytes) -> None:                                       # 最終（セッション13）
        voice_id = f"vc_{ULID()}"
        wav = pcm_to_wav(pcm, SAMPLE_RATE)
        path = self.state.voice_dir / f"{voice_id}.wav"
        await anyio.to_thread.run_sync(write_new, path, wav)
        self.state.data.add("voice", voice_id, self.user_id, path=path)
        log.info("voice_saved", extra={"fields": {"user_id": self.user_id, "voice_id": voice_id, "bytes": len(wav),
                                                  "audio_seconds": round(len(pcm) / (SAMPLE_RATE * 2), 3)}})

    async def transcribe(self, pcm: bytes) -> str:
        try:                                                                              # 最終：入口を通す
            res = await self.state.stt_gate.run_sync(self.state.transcriber, pcm16_to_float32(pcm), SAMPLE_RATE)
        except Busy:
            raise TurnFailed("stt_busy", MSG_STT_BUSY) from None
        self.state.usage.add_audio(self.user_id, "stt", f"whisper:{settings.whisper_model}",
                                   res.audio_seconds, res.processing_seconds, self.request_id)
        return res.text.strip()

    def sentence_buffer(self) -> SentenceBuffer:
        return SentenceBuffer()

    async def reply(self, t: TurnTimes) -> None:
        sentences: asyncio.Queue[str | None] = asyncio.Queue()
        system = system_with_pantry(SYSTEM, pantry_names(self.state.data, self.user_id))   # 最終

        async def think() -> None:
            buf = self.sentence_buffer()
            req = ChatRequest(messages=self.history.snapshot(), system=system,
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
                            self.state.usage.add_llm(self.user_id, settings.llm_model, ev.usage, self.request_id)
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
                    r = await self.state.tts_gate.run(vv.synthesize, sentence, sample_rate=OUTPUT_RATE)  # 最終
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
            except Busy:                                                                  # 最終
                raise TurnFailed("tts_busy", MSG_TTS_BUSY) from None
            except httpx2.HTTPError:
                raise TurnFailed("tts_unavailable", MSG_TTS) from None
            finally:
                if index:
                    self.state.usage.add_audio(self.user_id, "tts", f"voicevox:{vv.speaker}",
                                               audio_s, proc_s, self.request_id)

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(think())
                tg.create_task(speak())
        except ExceptionGroup as group:
            failed = [e for e in group.exceptions if isinstance(e, TurnFailed)]
            if not failed:
                raise
            raise failed[0] from None
