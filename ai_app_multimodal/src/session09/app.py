"""セッション9：音声合成のエンドポイント。

- GET  /health           … 生存確認
- POST /api/voice/speak  … {text} → audio/wav（24kHz・モノラル）＋ヘッダ x-voice-credit

    APP_MODULE=src.session09.app:app docker compose up -d api
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote

import httpx2
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from ulid import ULID

from kondate.settings import get_settings
from kondate.tts import Voicevox
from kondate.usage import UsageLog
from src.session09.sentences import split_sentences
from src.session09.wavs import join_wavs

settings = get_settings()

SPEAK_MAX_CHARS = 500                 # 合成は CPU を使うので、1回に読み上げる長さを制限する
OUTPUT_RATE = 24000                   # 再生用は 24kHz（音声認識用の 16kHz とは別）
# HTTP ヘッダの値は latin-1 しか使えないので、日本語のクレジットはパーセントエンコードして載せる
CREDIT_HEADER = quote(settings.voicevox_credit, safe=":")


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=SPEAK_MAX_CHARS)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.voicevox = Voicevox()
    app.state.usage = UsageLog()
    yield
    await app.state.voicevox.aclose()


app = FastAPI(title="こんだてAI セッション9", lifespan=lifespan)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = f"req_{ULID()}"
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


def error(request: Request, status: int, type_: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"type": type_, "message": message, "request_id": request.state.request_id}},
        status_code=status,
    )


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    field = str(errors[0]["loc"][-1]) if errors else "request"
    return error(request, 422, "invalid_request", f"入力値が正しくありません：{field}")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/voice/speak")
async def speak(request: Request, body: SpeakIn, x_user_id: str = Header(default="u001")) -> Response:
    sentences = split_sentences(body.text)
    if not sentences:                                  # 記号や空白だけで、読む文字がない
        return error(request, 422, "invalid_request", "入力値が正しくありません：text")

    vv: Voicevox = request.app.state.voicevox
    try:
        await vv.ensure_user_dict()                    # VOICEVOX が再起動すると辞書が消えるので、毎回確かめる
        parts = [await vv.synthesize(s, sample_rate=OUTPUT_RATE) for s in sentences]
    except httpx2.HTTPError:
        return error(request, 503, "tts_unavailable", "音声合成エンジンに接続できませんでした")

    request.app.state.usage.add(
        x_user_id, "tts", f"voicevox:{vv.speaker}",
        audio_seconds=round(sum(p.audio_seconds for p in parts), 3),
        processing_seconds=round(sum(p.processing_seconds for p in parts), 3),
        request_id=request.state.request_id,
    )
    return Response(join_wavs([p.wav for p in parts]), media_type="audio/wav",
                    headers={"x-voice-credit": CREDIT_HEADER})
