"""WS /ws/voice の1本の接続を受け持つ（セッション10の session.py をコピーし、同意・保存・ログを足した）。

セッション10から変えたのは次の3点だけ（「# S13」の印を付けた行）。
1. start の store_audio（追加のキー）が JSON の true のときだけ、発話の音声を保存する。無い・true 以外は「保存しない」
   ready に store_audio を足して、サーバーがどちらで受け付けたかを画面へ返す
2. 保存するのは VAD が切り出した1発話の音声だけ（WAV・保持期限7日）。台帳（state.data）に持ち主と期限を記録する
3. 文字起こしはログに出さない。長さと SHA256 の先頭12桁だけを記録する
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
import wave
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
from src.session13.latency import TurnTimes
from src.session13.logmask import sha12
from src.session13.sentence_buffer import SentenceBuffer
from src.session13.vad import SAMPLE_RATE, UtteranceDetector

settings = get_settings()
log = logging.getLogger(__name__)                 # S13：src.session13 のハンドラでマスクされる
UPLINK_BYTES = SAMPLE_RATE * 20 // 1000 * 2      # 20ms の PCM 16bit ＝ 320 サンプル × 2 バイト ＝ 640 バイト
OUTPUT_RATE = 24000                               # 再生用（セッション9と同じ）
POLICY_VIOLATION = 1008                           # 取り決めに反するメッセージを受けたときの close コード
SYSTEM = "あなたは献立相談AIです。返答は音声で読み上げるので、短い文で答えてください。"
MSG_START = '最初に {"type":"start","sample_rate":16000} を送ってください'
MSG_FRAME = f"音声は 20ms（{UPLINK_BYTES} バイト）ずつ送ってください"
MSG_CONTROL = "テキストで送れるのは start と stop だけです"
MSG_UPSTREAM = "返答の生成に失敗しました。時間をおいて試してください"
MSG_TTS = "音声合成エンジンに接続できませんでした"


class TurnFailed(Exception):
    """ターンを続けられない理由。上流の生のエラー文は持たせず、種別と日本語の固定文だけにする。"""

    def __init__(self, type_: str, message: str) -> None:
        super().__init__(message)
        self.type, self.message = type_, message


def parse_control(text: str) -> dict | None:
    """テキストのメッセージを辞書にする。JSON でない・辞書でないときは None。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def wants_storage(start: dict) -> bool:                                   # S13
    """保存してよいのは、利用者がはっきり同意したとき（JSON の true）だけ。"true"・1・無しは「保存しない」。"""
    return start.get("store_audio") is True


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:                          # S13
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return out.getvalue()


def write_new(path: Path, data: bytes) -> None:                          # S13
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:                     # 同じ名前があれば上書きせずに失敗する
        f.write(data)


class VoiceSession:
    def __init__(self, ws: WebSocket, state: Any, user_id: str = "u001",
                 detector: UtteranceDetector | None = None) -> None:
        self.ws, self.state, self.user_id = ws, state, user_id
        self.request_id = f"req_{ULID()}"            # エラーに付ける ID（接続ごとに1つ）
        self.detector = detector or UtteranceDetector()
        self.turn: asyncio.Task | None = None        # 返答を作っている間だけ入っている
        self.last_voice_at = 0.0
        self.store_audio = False                     # S13：既定は「保存しない」
        self._send_lock = asyncio.Lock()

    # ---- 送信：受信ループとターンの両方から呼ばれるので、ロックで1通ずつにする ----
    async def send(self, payload: dict) -> None:
        async with self._send_lock:
            await self.ws.send_json(payload)

    async def send_audio(self, index: int, text: str, wav: bytes) -> None:
        async with self._send_lock:                  # audio の JSON と WAV の間に、別のメッセージを割り込ませない
            await self.ws.send_json({"type": "audio", "index": index, "text": text,
                                     "sample_rate": OUTPUT_RATE, "bytes": len(wav)})
            await self.ws.send_bytes(wav)

    async def send_error(self, type_: str, message: str) -> None:
        await self.send({"type": "error",
                         "error": {"type": type_, "message": message, "request_id": self.request_id}})

    async def reject(self, message: str) -> None:
        """取り決めに反するメッセージ：理由を送ってから閉じる。"""
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
            self.store_audio = wants_storage(start)                                       # S13
            log.info("voice_start", extra={"fields": {"user_id": self.user_id, "request_id": self.request_id,
                                                      "store_audio": self.store_audio}})
            await self.send({"type": "ready", "credit": settings.voicevox_credit,
                             "store_audio": self.store_audio})                            # S13：追加のキー
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
                self.turn.cancel()                   # 相手が切れたら、作りかけの返答は捨てる

    async def on_control(self, data: dict | None) -> bool:
        """テキストのメッセージ。接続を続けるなら True。"""
        if data is not None and data.get("type") == "stop":
            if self.turn is not None:
                await self.turn                      # 返答の途中なら、最後まで送ってから閉じる
            await self.ws.close(code=1000)
            return False
        await self.reject(MSG_CONTROL)
        return False

    async def on_audio(self, data: bytes) -> bool:
        """20ms の PCM。接続を続けるなら True。"""
        if len(data) != UPLINK_BYTES:
            await self.reject(MSG_FRAME)
            return False
        if self.turn is not None:
            return True                              # 返答を作っている間の音声は VAD に渡さずに捨てる
        before = self.detector.last_voiced_frame
        events = self.detector.push(data)
        now = time.perf_counter()
        if self.detector.last_voiced_frame != before:
            self.last_voice_at = now
        for ev in events:
            await self.send({"type": "vad", "state": ev.kind})
            if ev.kind == "speech_end":
                self.start_turn(ev.audio, TurnTimes(last_voice=self.last_voice_at, speech_end=now))
                break
        return True

    # ---- ターン：（同意があれば保存）→ 認識 → LLM（ストリーミング）→ 文ごとの合成 ----
    def start_turn(self, pcm: bytes, times: TurnTimes) -> None:
        self.turn = asyncio.create_task(self.run_turn(pcm, times))

    async def run_turn(self, pcm: bytes, t: TurnTimes) -> None:
        try:
            if self.store_audio:                     # S13：同意があるときだけ
                await self.keep_audio(pcm)
            text = await self.transcribe(pcm)
            t.transcript = time.perf_counter()
            log.info("transcript", extra={"fields": {"user_id": self.user_id, "request_id": self.request_id,
                                                     "chars": len(text), "sha12": sha12(text)}})   # S13：中身は出さない
            await self.send({"type": "transcript", "text": text})
            if text:
                await self.reply(text, t)
            await self.send({"type": "turn_end", "latency_ms": t.latency_ms()})
        except TurnFailed as e:
            await self.send_error(e.type, e.message)
        finally:
            self.detector.reset()
            self.turn = None

    async def keep_audio(self, pcm: bytes) -> None:                                       # S13
        """VAD が切り出した1発話を WAV で保存し、台帳に持ち主と期限（7日）を記録する。"""
        voice_id = f"vc_{ULID()}"
        wav = pcm_to_wav(pcm, SAMPLE_RATE)
        path = self.state.voice_dir / f"{voice_id}.wav"   # 名前はサーバーが採番する（利用者の名前・日時を入れない）
        await anyio.to_thread.run_sync(write_new, path, wav)
        self.state.data.add("voice", voice_id, self.user_id, path=path)
        log.info("voice_saved", extra={"fields": {"user_id": self.user_id, "voice_id": voice_id, "bytes": len(wav),
                                                  "audio_seconds": round(len(pcm) / (SAMPLE_RATE * 2), 3)}})

    async def transcribe(self, pcm: bytes) -> str:
        res = await anyio.to_thread.run_sync(
            self.state.transcriber, pcm16_to_float32(pcm), SAMPLE_RATE,
            limiter=self.state.stt_limiter,
        )
        self.state.usage.add(self.user_id, "stt", f"whisper:{settings.whisper_model}",
                             audio_seconds=round(res.audio_seconds, 3),
                             processing_seconds=round(res.processing_seconds, 3), request_id=self.request_id)
        return res.text.strip()

    def sentence_buffer(self) -> SentenceBuffer:
        return SentenceBuffer()

    async def reply(self, text: str, t: TurnTimes) -> None:
        sentences: asyncio.Queue[str | None] = asyncio.Queue()

        async def think() -> None:
            buf = self.sentence_buffer()
            req = ChatRequest(messages=[{"role": "user", "content": text}], system=SYSTEM,
                              max_tokens=settings.llm_max_tokens)
            try:
                async for ev in self.state.llm.stream(req):
                    if isinstance(ev, TextDelta):
                        await self.send({"type": "reply_delta", "text": ev.text})
                        for s in buf.feed(ev.text):
                            t.sentence_ready(time.perf_counter())
                            sentences.put_nowait(s)
                    elif isinstance(ev, Done):
                        self.state.usage.add(self.user_id, "llm", settings.llm_model,
                                             input_tokens=ev.usage.input_tokens,
                                             output_tokens=ev.usage.output_tokens, request_id=self.request_id)
            except (anthropic.APIError, httpx2.HTTPError):
                raise TurnFailed("upstream_unavailable", MSG_UPSTREAM) from None
            for s in buf.flush():
                t.sentence_ready(time.perf_counter())
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
                        t.tts_first = time.perf_counter()
                    await self.send_audio(index, sentence, r.wav)
                    if index == 0:
                        t.first_audio = time.perf_counter()
                    index += 1
                    audio_s += r.audio_seconds
                    proc_s += r.processing_seconds
            except httpx2.HTTPError:
                raise TurnFailed("tts_unavailable", MSG_TTS) from None
            if index:
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
