"""音声の入口：POST /api/voice/transcribe・/speak・/loopback、GET /（画面）、WS /ws/voice。

- transcribe … セッション8＋14（入口 stt_gate）
- speak … セッション9（文に分けて合成し、つなぐ）＋14（入口 tts_gate。1リクエストで1回だけ並ぶ）
- loopback … 環境構築の章（kondate/main.py）の閉ループ検査を、入口と利用量の帳簿に通したもの
- WS /ws/voice … session.VoiceSession（セッション11の割り込み＋13の同意＋14の入口）
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import anyio
import httpx2
from fastapi import APIRouter, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from kondate.audio import wav_to_float32
from kondate.metrics import cer
from kondate.settings import get_settings
from kondate.tts import Voicevox
from src.final.audio_in import AudioRejected, decode_wav
from src.final.gate import Busy
from src.final.intake import MSG_TOO_LARGE
from src.final.sentences import split_sentences
from src.final.session import MSG_STT_BUSY, MSG_TTS_BUSY, OUTPUT_RATE, POLICY_VIOLATION, VoiceSession
from src.final.wavs import join_wavs
from src.final.web import USER_ID_RE, UserId, busy, error

settings = get_settings()
router = APIRouter()

STATIC = Path(__file__).parent / "static"
ALLOWED_ORIGINS = {"http://localhost:8720", "http://127.0.0.1:8720"}
SPEAK_MAX_CHARS = 500
CREDIT_HEADER = quote(settings.voicevox_credit, safe=":")   # ヘッダは latin-1 だけなのでパーセントエンコードする
LOOPBACK_TEXT = "鶏むね肉とキャベツで20分で作れる料理は？"
LOOPBACK_MAX_CHARS = 100
LOOPBACK_CER_MAX = 0.10
MSG_TTS_UNAVAILABLE = "音声合成エンジンに接続できませんでした"
MSG_NOTHING_TO_SAY = "入力値が正しくありません：text"


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=SPEAK_MAX_CHARS)


class LoopbackIn(BaseModel):
    text: str = Field(default=LOOPBACK_TEXT, min_length=1, max_length=LOOPBACK_MAX_CHARS)


@router.post("/api/voice/transcribe")
async def transcribe(request: Request, audio: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await audio.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_TOO_LARGE)
    try:
        samples = await anyio.to_thread.run_sync(decode_wav, raw)   # 音声は保存しない（メモリの中だけ）
    except AudioRejected as e:
        return error(request, e.status, e.type, e.message)
    s = request.app.state
    try:
        res = await s.stt_gate.run_sync(s.transcriber, samples, settings.stt_sample_rate)
    except Busy:
        return busy(request, "stt_busy", MSG_STT_BUSY)
    s.usage.add_audio(x_user_id, "stt", f"whisper:{settings.whisper_model}", res.audio_seconds,
                      res.processing_seconds, request.state.request_id)
    return JSONResponse({"text": res.text, "audio_seconds": round(res.audio_seconds, 2), "rtf": round(res.rtf, 2)})


@router.post("/api/voice/speak")
async def speak(request: Request, body: SpeakIn, x_user_id: UserId = "u001") -> Response:
    sentences = split_sentences(body.text)
    if not sentences:                                   # 記号や空白だけで、読む文字がない
        return error(request, 422, "invalid_request", MSG_NOTHING_TO_SAY)
    s = request.app.state
    vv = s.voicevox

    async def synthesize_all() -> list:
        return [await vv.synthesize(sentence, sample_rate=OUTPUT_RATE) for sentence in sentences]

    try:
        await vv.ensure_user_dict()
        parts = await s.tts_gate.run(synthesize_all)    # 1リクエストで入口に1回だけ並ぶ（文ごとに並び直さない）
    except Busy:
        return busy(request, "tts_busy", MSG_TTS_BUSY)
    except httpx2.HTTPError:
        return error(request, 503, "tts_unavailable", MSG_TTS_UNAVAILABLE)
    s.usage.add_audio(x_user_id, "tts", f"voicevox:{vv.speaker}", sum(p.audio_seconds for p in parts),
                      sum(p.processing_seconds for p in parts), request.state.request_id)
    return Response(join_wavs([p.wav for p in parts]), media_type="audio/wav",
                    headers={"x-voice-credit": CREDIT_HEADER})


@router.post("/api/voice/loopback")
async def voice_loopback(request: Request, body: LoopbackIn | None = None, x_user_id: UserId = "u001") -> JSONResponse:
    body = body or LoopbackIn()
    s = request.app.state
    vv: Voicevox = s.voicevox
    try:
        await vv.ensure_user_dict()
        tts = await s.tts_gate.run(vv.synthesize, body.text, sample_rate=settings.stt_sample_rate)
        audio, rate = wav_to_float32(tts.wav)
        res = await s.stt_gate.run_sync(s.transcriber, audio, rate)
    except Busy as e:
        return busy(request, f"{e.gate}_busy", MSG_STT_BUSY if e.gate == "stt" else MSG_TTS_BUSY)
    except httpx2.HTTPError:
        return error(request, 503, "tts_unavailable", MSG_TTS_UNAVAILABLE)
    score = round(cer(body.text, res.text), 4)
    rid = request.state.request_id
    s.usage.add_audio(x_user_id, "tts", f"voicevox:{vv.speaker}", tts.audio_seconds, tts.processing_seconds, rid)
    s.usage.add_audio(x_user_id, "stt", f"whisper:{settings.whisper_model}", res.audio_seconds,
                      res.processing_seconds, rid)
    return JSONResponse({
        "text": body.text,
        "kana": tts.kana,
        "transcript": res.text,
        "cer": score,
        "passed": score <= LOOPBACK_CER_MAX,
        "tts": {"audio_seconds": round(tts.audio_seconds, 2), "processing_seconds": round(tts.processing_seconds, 2),
                "rtf": round(tts.rtf, 2)},
        "stt": {"model": settings.whisper_model, "processing_seconds": round(res.processing_seconds, 2),
                "rtf": round(res.rtf, 2)},
        "credit": settings.voicevox_credit,
    })


@router.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "voice.html", media_type="text/html; charset=utf-8")


async def accept_voice(ws: WebSocket) -> str | None:
    """Origin（セッション10）と利用者 ID の形を確かめてから受け付ける。受け付けたら利用者 ID を返す。"""
    origin = ws.headers.get("origin")
    user_id = ws.headers.get("x-user-id", "u001")
    if (origin is not None and origin not in ALLOWED_ORIGINS) or not USER_ID_RE.match(user_id):
        await ws.close(code=POLICY_VIOLATION)
        return None
    await ws.accept()
    return user_id


@router.websocket("/ws/voice")
async def voice(ws: WebSocket) -> None:
    if (user_id := await accept_voice(ws)) is not None:
        state = ws.app.state
        await VoiceSession(ws, state, user_id=user_id, detector=state.make_detector()).run()
