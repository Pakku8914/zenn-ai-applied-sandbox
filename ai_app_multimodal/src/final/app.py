"""最終プロジェクト：声で相談できるこんだてAI（HTTP API の一覧と WebSocket の取り決めのすべて）。

    APP_MODULE=src.final.app:app docker compose up -d --wait api
    ブラウザで http://localhost:8720/ を開く

エンドポイントの一覧と評価の手順は src/final/README.md。ここでは、横断の仕組み
（request_id・エラー本文・ログのマスク・台帳と保持期限・利用量・応答キャッシュ・CPU の入口・ウォームアップ）を組み立てる。
状態はすべてプロセス内のメモリにある（再起動すると消える）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
from anthropic import AsyncAnthropic
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from ulid import ULID

from kondate import __version__, stt
from kondate.clock import SystemClock
from kondate.jobs import JobQueue
from kondate.llm import AnthropicProvider
from kondate.settings import get_settings
from kondate.tts import Voicevox
from kondate.usage import UsageLog
from src.final import api_documents, api_me, api_media, api_voice
from src.final.cache import ResponseCache
from src.final.gate import CpuGate
from src.final.logmask import setup_logging
from src.final.privacy import PersonalStore
from src.final.session import OUTPUT_RATE
from src.final.usage_book import UsageBook
from src.final.vad import UtteranceDetector
from src.final.warmup import Warmup, default_warmers
from src.final.web import error, on_validation_error

settings = get_settings()
setup_logging("src.final")                     # src.final 配下のロガーの記録をマスクして出す
log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
SWEEP_INTERVAL_SECONDS = 600                   # 掃除の間隔（実時間）。期限切れかどうかの判定は注入した時計で行う
CACHE_MAX_ENTRIES = 256
CACHE_TTL_SECONDS = 24 * 3600                  # 台帳の最短の保持期限（upload 24時間）を超えない
STT_CONCURRENCY, STT_MAX_WAITING = 1, 2
TTS_CONCURRENCY, TTS_MAX_WAITING = 1, 3


# ---------------------------------------------------------------- 期限切れの掃除（セッション13）

def sweep_once(state: Any) -> dict[str, int]:
    removed = state.data.sweep()
    if any(removed.values()):
        log.info("retention_sweep", extra={"fields": removed})
    return removed


async def sweep_forever(state: Any, interval: float = SWEEP_INTERVAL_SECONDS) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            sweep_once(state)
        except Exception:
            log.exception("retention_sweep_failed")


# ---------------------------------------------------------------- 組み立て

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """起動のたびに状態を作り直す。時計（clock）とウォームアップ（warmers）は、検証が起動の前に差し替えられる。"""
    s = app.state
    client = AsyncAnthropic()                  # 接続先とキーは環境変数 ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む
    voicevox = Voicevox()
    s.llm = AnthropicProvider(client)
    s.voicevox = voicevox
    s.data = PersonalStore(s.clock)            # 台帳：アップロード・食材名・文書・レシート・音声（保持期限つき）
    s.usage = UsageBook(UsageLog(s.clock))
    s.cache = ResponseCache(s.clock, CACHE_MAX_ENTRIES, CACHE_TTL_SECONDS)
    s.jobs = JobQueue(concurrency=1)
    s.job_owners = {}
    s.stt_gate = CpuGate("stt", STT_CONCURRENCY, STT_MAX_WAITING)
    s.tts_gate = CpuGate("tts", TTS_CONCURRENCY, TTS_MAX_WAITING)
    s.transcriber = stt.transcribe
    s.make_detector = UtteranceDetector
    s.warmup = Warmup(default_warmers(s, OUTPUT_RATE) if s.warmers is None else s.warmers)
    s.warmup.start()                           # 待たずに起動を終える（/health はすぐ 200）
    sweeper = asyncio.create_task(sweep_forever(s))
    yield
    sweeper.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await sweeper
    await s.warmup.stop()
    await voicevox.aclose()
    await client.close()


app = FastAPI(title="こんだてAI 最終プロジェクト：声で相談できるこんだてAI", version=__version__, lifespan=lifespan)
app.state.clock = SystemClock()                # 検証では FixedClock に差し替える
app.state.warmers = None                       # None なら本物のウォームアップ。検証では {} などに差し替える
app.state.upload_dir = Path("out/uploads")
app.state.voice_dir = Path("out/voice")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(api_media.router)
app.include_router(api_documents.router)
app.include_router(api_voice.router)
app.include_router(api_me.router)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = f"req_{ULID()}"
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


async def on_job_not_found(request: Request, exc: api_documents.JobNotFound) -> JSONResponse:
    return error(request, 404, "not_found", api_documents.MSG_JOB_NOT_FOUND)


app.add_exception_handler(RequestValidationError, on_validation_error)
app.add_exception_handler(api_documents.JobNotFound, on_job_not_found)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/health/deps")
async def health_deps(request: Request) -> JSONResponse:
    s = request.app.state
    deps: dict[str, str] = {}
    try:
        async with httpx2.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.mockllm_url}/_mock/health")
        deps["mockllm"] = "ok" if r.status_code == 200 else f"ng ({r.status_code})"
    except Exception as e:  # 疎通確認なので種類を問わず NG として返す
        deps["mockllm"] = f"ng ({type(e).__name__})"
    try:
        await s.voicevox.version()
        deps["voicevox"] = "ok"
    except Exception as e:
        deps["voicevox"] = f"ng ({type(e).__name__})"
    ready = all(v == "ok" for v in deps.values()) and s.warmup.ready
    return JSONResponse({
        "status": "ok" if ready else "ng",
        "deps": deps,
        "warmup": dict(s.warmup.state),
        "gates": {"stt": s.stt_gate.stats(), "tts": s.tts_gate.stats()},
    }, status_code=200 if ready else 503)
