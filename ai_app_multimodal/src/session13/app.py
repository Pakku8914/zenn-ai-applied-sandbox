"""セッション13：プライバシーと安全（保持期限・同意・データ削除・ログのマスク）。

- GET    /health          … 生存確認
- GET    /                … 音声対話の画面（マイクと保存の説明・保存の同意（既定はオフ）・自分のデータの削除）
- WS     /ws/voice        … セッション10の音声対話＋同意したときだけ発話を保存（start の store_audio）
- POST   /api/uploads     … セッション2の受付＋持ち主と保持期限（24時間）の記録
- POST   /api/documents   … PDF をメモリに登録（30日）
- DELETE /api/me/data     … 自分のアップロード・文書・レシート・音声・利用記録を消す

レシートの読み取り（セッション7）はここでは持たず、台帳の種別 "receipt"（30日）として同じ仕組みで扱う。

    APP_MODULE=src.session13.app:app docker compose up -d --wait api
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import anyio
from anthropic import AsyncAnthropic
from fastapi import FastAPI, Header, Request, UploadFile, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader
from ulid import ULID

from kondate import __version__, stt
from kondate.clock import SystemClock
from kondate.llm import AnthropicProvider
from kondate.settings import get_settings
from kondate.tts import Voicevox
from kondate.usage import UsageLog
from src.session13.intake import MSG_TOO_LARGE, Rejected, inspect_upload, save_upload
from src.session13.logmask import setup_logging
from src.session13.privacy import PersonalStore
from src.session13.session import POLICY_VIOLATION, VoiceSession
from src.session13.vad import UtteranceDetector

settings = get_settings()
setup_logging("src.session13")                    # このパッケージ（.app・.session など）の記録をマスクして出す
log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
ALLOWED_ORIGINS = {"http://localhost:8720", "http://127.0.0.1:8720"}
SWEEP_INTERVAL_SECONDS = 600                       # 掃除の間隔（実時間）。何が期限切れかの判定は注入した時計で行う
MSG_NOT_PDF = "PDF を送ってください"

UserId = Annotated[str, Header(alias="x-user-id", pattern=r"^u\d{3}$")]   # 認証は①に任せ、ヘッダで代用する


# ---------------------------------------------------------------- 期限切れの掃除

def sweep_once(state: Any) -> dict[str, int]:
    removed = state.data.sweep()
    if any(removed.values()):
        log.info("retention_sweep", extra={"fields": removed})
    return removed


async def sweep_forever(state: Any, interval: float = SWEEP_INTERVAL_SECONDS) -> None:
    """一定の間隔で掃除を続ける。1回の失敗でタスクが止まらないよう、例外は記録して次の回へ進む。"""
    while True:
        await asyncio.sleep(interval)
        try:
            sweep_once(state)
        except Exception:
            log.exception("retention_sweep_failed")   # 記録されるのは例外の種類だけ（パスなどは出ない）


# ---------------------------------------------------------------- アプリ

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = AsyncAnthropic()                        # 接続先とキーは環境変数 ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む
    app.state.llm = AnthropicProvider(client)
    app.state.voicevox = Voicevox()
    app.state.usage = UsageLog(app.state.clock)      # 中身（文字起こし・画像）を入れる欄はない
    app.state.stt_limiter = anyio.CapacityLimiter(1)
    app.state.transcriber = stt.transcribe
    app.state.make_detector = UtteranceDetector      # 検証で差し替えられるよう state に置く
    sweeper = asyncio.create_task(sweep_forever(app.state))
    yield
    sweeper.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await sweeper
    await app.state.voicevox.aclose()
    await client.close()


app = FastAPI(title="こんだてAI セッション13：プライバシーと安全", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.state.clock = SystemClock()                      # 保持期限の判定に使う。verify では FixedClock に差し替える
app.state.data = PersonalStore(app.state.clock)
app.state.upload_dir = Path("out/uploads")
app.state.voice_dir = Path("out/voice")


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


async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # 入力値（input）は返さない。どの項目かだけを返す
    names = dict.fromkeys(str(e["loc"][-1]) for e in exc.errors())
    return error(request, 422, "invalid_request", f"入力値が正しくありません：{'、'.join(names)}")


app.add_exception_handler(RequestValidationError, on_validation_error)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "voice.html", media_type="text/html; charset=utf-8")


@app.post("/api/uploads")
async def create_upload(request: Request, file: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await file.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_TOO_LARGE)
    try:
        kind, ext = await anyio.to_thread.run_sync(inspect_upload, raw)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)

    upload_id = f"up_{ULID()}"
    path = await anyio.to_thread.run_sync(save_upload, request.app.state.upload_dir, upload_id, ext, raw)
    request.app.state.data.add("upload", upload_id, x_user_id, path=path)      # 持ち主と期限（24時間）を記録
    digest = hashlib.sha256(raw).hexdigest()
    # file.filename はログにも出さない（「山田家の冷蔵庫.jpg」のように名前や住所が入っていることがある）
    log.info("upload_saved", extra={"fields": {"user_id": x_user_id, "upload_id": upload_id, "kind": kind,
                                               "bytes": len(raw), "sha12": digest[:12]}})
    return JSONResponse({"upload_id": upload_id, "kind": kind, "bytes": len(raw), "sha256": digest},
                        status_code=201)


def count_pdf_pages(raw: bytes) -> int:
    kind, _ = inspect_upload(raw)
    if kind != "pdf":
        raise Rejected(415, "unsupported_media", MSG_NOT_PDF)
    return len(PdfReader(io.BytesIO(raw)).pages)


@app.post("/api/documents")
async def create_document(request: Request, file: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await file.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_TOO_LARGE)
    try:
        pages = await anyio.to_thread.run_sync(count_pdf_pages, raw)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)
    document_id = f"doc_{ULID()}"
    request.app.state.data.add("document", document_id, x_user_id, data=raw)  # メモリに持つ（30日）
    digest = hashlib.sha256(raw).hexdigest()
    log.info("document_saved", extra={"fields": {"user_id": x_user_id, "document_id": document_id,
                                                 "pages": pages, "bytes": len(raw)}})
    return JSONResponse({"document_id": document_id, "pages": pages, "sha256": digest}, status_code=201)


def forget_usage(usage: UsageLog, user_id: str) -> int:
    """利用記録から、その利用者の行を消して件数を返す（メモリの記録。JSON Lines に書き出していればそちらも要る）。"""
    before = len(usage.records)
    usage.records[:] = [r for r in usage.records if r.user_id != user_id]
    return before - len(usage.records)


@app.delete("/api/me/data")
async def delete_my_data(request: Request, x_user_id: Annotated[str, Header(alias="x-user-id",
                                                                         pattern=r"^u\d{3}$")]) -> dict:
    """自分のデータを消す。x-user-id は必須（消す操作に「既定の利用者」を使わない）。2回目は 0 件を返す。"""
    deleted = request.app.state.data.delete_user(x_user_id)
    deleted["usage"] = forget_usage(request.app.state.usage, x_user_id)
    log.info("data_deleted", extra={"fields": {"user_id": x_user_id, **deleted}})
    return {"deleted": deleted}


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
        state = ws.app.state
        await VoiceSession(ws, state, user_id=ws.headers.get("x-user-id", "u001"),
                           detector=state.make_detector()).run()
