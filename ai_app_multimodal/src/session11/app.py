"""セッション11：割り込み（barge-in）とターン制御。

- GET  /health    … 生存確認
- GET  /          … 音声対話の1ページ（static/voice.html。読み上げ中も話しかけられる）
- WS   /ws/voice  … API契約⑤（セッション10に interrupted {index} を足した）

    APP_MODULE=src.session11.app:app docker compose up -d --wait api
    ブラウザで http://localhost:8720/ を開く
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from anthropic import AsyncAnthropic
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from kondate import stt
from kondate.llm import AnthropicProvider
from kondate.tts import Voicevox
from kondate.usage import UsageLog
from src.session11.session import POLICY_VIOLATION, VoiceSession

STATIC = Path(__file__).parent / "static"
ALLOWED_ORIGINS = {"http://localhost:8720", "http://127.0.0.1:8720"}


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


app = FastAPI(title="こんだてAI セッション11", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "voice.html", media_type="text/html; charset=utf-8")


async def accept_voice(ws: WebSocket) -> bool:
    """Origin を確かめてから接続を受け付ける（セッション10と同じ）。"""
    origin = ws.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        await ws.close(code=POLICY_VIOLATION)
        return False
    await ws.accept()
    return True


@app.websocket("/ws/voice")
async def voice(ws: WebSocket) -> None:
    if await accept_voice(ws):
        await VoiceSession(ws, ws.app.state, user_id=ws.headers.get("x-user-id", "u001")).run()
