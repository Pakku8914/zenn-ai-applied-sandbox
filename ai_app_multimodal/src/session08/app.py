"""セッション8：音声認識のエンドポイント。

- GET  /health                … 生存確認
- POST /api/voice/transcribe … multipart の audio（WAV）→ {text, audio_seconds, rtf}

    APP_MODULE=src.session08.app:app docker compose up -d api
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ulid import ULID

from kondate import stt
from kondate.settings import get_settings
from kondate.usage import UsageLog
from src.session08.audio_in import AudioRejected, decode_wav

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.usage = UsageLog()
    app.state.stt_limiter = anyio.CapacityLimiter(1)   # 認識は同時に1件（1件で cpu_threads=2 本の CPU を使う）
    app.state.transcriber = stt.transcribe              # 検証で差し替えられるよう state に置く
    yield


app = FastAPI(title="こんだてAI セッション8", lifespan=lifespan)


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
    return {"status": "ok"}      # compose の healthcheck が見る


@app.post("/api/voice/transcribe")
async def transcribe(request: Request, audio: UploadFile, x_user_id: str = Header(default="u001")) -> JSONResponse:
    raw = await audio.read(settings.upload_max_bytes + 1)          # 上限＋1バイトまでしか読まない
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", f"ファイルは {settings.upload_max_bytes // (1024 * 1024)}MB 以下にしてください")
    try:
        samples = await anyio.to_thread.run_sync(decode_wav, raw)  # 検査と 16kHz への変換（メモリの中だけで行う）
    except AudioRejected as e:
        return error(request, e.status, e.type, e.message)

    res = await anyio.to_thread.run_sync(
        request.app.state.transcriber, samples, settings.stt_sample_rate,
        limiter=request.app.state.stt_limiter,
    )
    request.app.state.usage.add(
        x_user_id, "stt", f"whisper:{settings.whisper_model}",
        audio_seconds=round(res.audio_seconds, 3), processing_seconds=round(res.processing_seconds, 3),
        request_id=request.state.request_id,
    )
    return JSONResponse({"text": res.text, "audio_seconds": round(res.audio_seconds, 2), "rtf": round(res.rtf, 2)})
