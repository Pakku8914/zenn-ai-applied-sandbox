"""セッション14：コストと運用 ― 利用量の記録・応答キャッシュ・同時実行数と待ち行列・ウォームアップ。

- GET  /health                        生存確認（依存先は見ない。ウォームアップ中も 200）
- GET  /health/deps                   準備ができたか（依存先＋ウォームアップ）。整うまで 503
- POST /api/fridge/scan               冷蔵庫の写真 → 食材リスト（応答キャッシュ付き）
- POST /api/documents                 PDF の登録
- POST /api/documents/{id}/ask        文書への質問（プロンプトキャッシュ＋応答キャッシュ）
- POST /api/voice/transcribe          音声認識（同時 1 件・待ち 2 件まで。あふれたら 503 stt_busy）
- POST /api/voice/speak               音声合成（同時 1 件・待ち 3 件まで。あふれたら 503 tts_busy）
- GET  /api/usage                     自分の利用量

起動：APP_MODULE=src.session14.app:app docker compose up -d --wait api
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated
from urllib.parse import quote

import anthropic
import anyio
import httpx2
from anthropic import AsyncAnthropic, transform_schema
from fastapi import Depends, FastAPI, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, ValidationError
from ulid import ULID

from kondate import __version__, stt
from kondate.clock import SystemClock
from kondate.llm import AnthropicProvider, ChatRequest, LLMProvider, Usage
from kondate.settings import get_settings
from kondate.tts import Voicevox
from kondate.usage import UsageLog
from src.session14.audio_in import AudioRejected, decode_wav
from src.session14.cache import ResponseCache, cache_key, sha256_hex
from src.session14.documents import cached, inspect_pdf, pdf_block, quote_exists
from src.session14.gate import Busy, CpuGate
from src.session14.intake import MSG_TOO_LARGE, Rejected, accept_image
from src.session14.models import FRIDGE_SCHEMA, FridgeScan
from src.session14.usage_book import UsageBook
from src.session14.warmup import Warmup, default_warmers

settings = get_settings()

# ---- 前の章と同じ値 ----
FRIDGE_PROMPT = "冷蔵庫の写真に写っている食材をすべて挙げてください。分量が分からないものは見た目から推定してください。"
SYSTEM_PROMPT = (
    "添付の文書だけを根拠に答えてください。"
    "根拠にした文は文書から一字一句そのまま写し、ページ番号（1始まり）と一緒に引用として示してください。"
)
MAX_ATTEMPTS = 2
OUTPUT_RATE = 24000
SPEAK_MAX_CHARS = 500
CREDIT_HEADER = quote(settings.voicevox_credit, safe=":")
MSG_SCAN_INVALID = "読み取り結果の形式が正しくありませんでした"
MSG_SCAN_UPSTREAM = "画像の読み取りに失敗しました。時間をおいて試してください"
MSG_NOT_FOUND = "文書が見つかりません"
MSG_DOC_UPSTREAM = "文書の読み取りに失敗しました。時間をおいて試してください"
MSG_UNGROUNDED = "回答の根拠を文書の中で確かめられませんでした"
MSG_TTS_UNAVAILABLE = "音声合成エンジンに接続できませんでした"

# ---- 本章で決めた値 ----
JPEG_QUALITY = 90
PREPROCESS = {"max_long_edge": settings.image_max_long_edge, "jpeg_quality": JPEG_QUALITY}
CACHE_MAX_ENTRIES = 256
CACHE_TTL_SECONDS = 24 * 3600          # セッション13の保持期限より短くする
STT_CONCURRENCY, STT_MAX_WAITING = 1, 2
TTS_CONCURRENCY, TTS_MAX_WAITING = 1, 3
RETRY_AFTER_SECONDS = 2
MSG_STT_BUSY = "音声認識が混み合っています。少し待ってから試してください"
MSG_TTS_BUSY = "音声合成が混み合っています。少し待ってから試してください"
ZERO_SCAN_USAGE = {"input_tokens": 0, "output_tokens": 0}
ZERO_ASK_USAGE = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}

UserId = Annotated[str, Header(alias="x-user-id", pattern=r"^u\d{3}$")]  # 認証は①に任せ、ヘッダで代用する


class Citation(BaseModel):
    page: int = Field(description="引用したページの番号（1始まり）")
    quote: str = Field(description="そのページから一字一句そのまま写した文")


class DocumentAnswer(BaseModel):
    answer: str
    citations: list[Citation]


ANSWER_SCHEMA = transform_schema(DocumentAnswer)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=SPEAK_MAX_CHARS)


@dataclass
class StoredDocument:
    document_id: str
    user_id: str
    sha256: str
    pages: int
    data: bytes = field(repr=False)
    page_texts: list[str] = field(repr=False)


class DocumentStore:
    def __init__(self) -> None:
        self._by_id: dict[str, StoredDocument] = {}
        self._by_hash: dict[tuple[str, str], str] = {}

    def find(self, user_id: str, sha256: str) -> StoredDocument | None:
        doc_id = self._by_hash.get((user_id, sha256))
        return self._by_id[doc_id] if doc_id else None

    def add(self, user_id: str, sha256: str, pages: int, data: bytes, texts: list[str]) -> StoredDocument:
        doc = StoredDocument(f"doc_{ULID()}", user_id, sha256, pages, data, texts)
        self._by_id[doc.document_id] = doc
        self._by_hash[(user_id, sha256)] = doc.document_id
        return doc

    def get(self, user_id: str, document_id: str) -> StoredDocument | None:
        doc = self._by_id.get(document_id)
        return doc if doc is not None and doc.user_id == user_id else None


# ---------------------------------------------------------------- アプリ

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = AsyncAnthropic()  # 接続先とキーは環境変数 ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む
    clock = SystemClock()
    s = app.state
    s.llm = AnthropicProvider(client)
    s.voicevox = Voicevox()
    s.usage = UsageBook(UsageLog(clock))
    s.cache = ResponseCache(clock, CACHE_MAX_ENTRIES, CACHE_TTL_SECONDS)
    s.documents = DocumentStore()
    s.stt_gate = CpuGate("stt", STT_CONCURRENCY, STT_MAX_WAITING)
    s.tts_gate = CpuGate("tts", TTS_CONCURRENCY, TTS_MAX_WAITING)
    s.transcriber = stt.transcribe               # 検証で差し替えられるよう state に置く
    warmers = getattr(s, "warmers", None)        # 検証では差し替えたものを使う
    s.warmup = Warmup(default_warmers(s, OUTPUT_RATE) if warmers is None else warmers)
    s.warmup.start()                             # 待たずに起動を終える（/health はすぐ 200 を返せる）
    yield
    await s.warmup.stop()
    await s.voicevox.aclose()
    await client.close()


app = FastAPI(title="こんだてAI セッション14：コストと運用", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = f"req_{ULID()}"
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


def error(request: Request, status: int, type_: str, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        {"error": {"type": type_, "message": message, "request_id": request.state.request_id}},
        status_code=status, headers=headers,
    )


def busy(request: Request, type_: str, message: str) -> JSONResponse:
    # 混雑は「少し待てば通る」失敗なので、待つ秒数の目安を Retry-After で知らせる
    return error(request, 503, type_, message, {"retry-after": str(RETRY_AFTER_SECONDS)})


async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    names = dict.fromkeys(str(e["loc"][-1]) for e in exc.errors())
    return error(request, 422, "invalid_request", f"入力値が正しくありません：{'、'.join(names)}")


app.add_exception_handler(RequestValidationError, on_validation_error)


def get_llm(request: Request) -> LLMProvider:
    """使う LLM。verify では dependency_overrides で FakeProvider に差し替える。"""
    return request.app.state.llm


Llm = Annotated[LLMProvider, Depends(get_llm)]


def total(used: list[Usage]) -> Usage:
    return Usage(
        sum(u.input_tokens for u in used), sum(u.output_tokens for u in used),
        sum(u.cache_read_input_tokens for u in used), sum(u.cache_creation_input_tokens for u in used),
    )


def record_llm(request: Request, user_id: str, used: list[Usage]) -> None:
    """失敗した試行も含めて、実際に使ったトークンを記録する（料金は失敗しても発生している）。"""
    if used:
        request.app.state.usage.add_llm(user_id, settings.llm_model, total(used), request.state.request_id)


# ---------------------------------------------------------------- 生存確認と準備の確認

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


# ---------------------------------------------------------------- 冷蔵庫の写真（応答キャッシュ）

async def scan_fridge(llm: LLMProvider, jpeg: bytes, used: list[Usage]) -> FridgeScan | None:
    """形が正しくなければ1回だけ再試行する（セッション4）。使ったトークンは used に足していく。"""
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(jpeg).decode("ascii")}}
    req = ChatRequest(messages=[{"role": "user", "content": [image, {"type": "text", "text": FRIDGE_PROMPT}]}],
                      output_schema=FRIDGE_SCHEMA, max_tokens=settings.llm_max_tokens)
    for _ in range(MAX_ATTEMPTS):
        result = await llm.complete(req)  # 上流のエラーはそのまま上げる
        used.append(result.usage)
        if result.stop_reason == "max_tokens":
            return None
        try:
            return FridgeScan.model_validate_json(result.text)
        except ValidationError:
            continue
    return None


@app.post("/api/fridge/scan")
async def fridge_scan(request: Request, image: UploadFile, llm: Llm, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await image.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_TOO_LARGE)
    s = request.app.state
    key = cache_key(scope=x_user_id, kind="fridge_scan", content_sha256=sha256_hex(raw), preprocess=PREPROCESS,
                    prompt=FRIDGE_PROMPT, system=None, model=settings.llm_model, schema=FRIDGE_SCHEMA)
    if (hit := s.cache.get(key)) is not None:
        s.usage.count_lookup(x_user_id, hit=True)          # LLM を呼んでいないので、トークンは足さない
        return JSONResponse({**hit.value, "usage": ZERO_SCAN_USAGE}, headers={"x-cache": "hit"})
    s.usage.count_lookup(x_user_id, hit=False)

    try:
        prepared = await anyio.to_thread.run_sync(accept_image, raw, PREPROCESS["max_long_edge"], JPEG_QUALITY)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)
    used: list[Usage] = []
    try:
        scan = await scan_fridge(llm, prepared.data, used)
    except anthropic.APIError:
        return error(request, 503, "upstream_unavailable", MSG_SCAN_UPSTREAM)
    finally:
        record_llm(request, x_user_id, used)
    if scan is None:
        return error(request, 502, "invalid_output", MSG_SCAN_INVALID)  # 失敗はキャッシュしない

    value = {"ingredients": [i.model_dump() for i in scan.ingredients], "image": prepared.info()}
    u = total(used)
    s.cache.put(key, x_user_id, value, u)
    return JSONResponse({**value, "usage": {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens}},
                        headers={"x-cache": "miss"})


# ---------------------------------------------------------------- 文書（プロンプトキャッシュ＋応答キャッシュ）

@app.post("/api/documents")
async def create_document(request: Request, file: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await file.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", f"ファイルは {settings.upload_max_bytes // (1024 * 1024)}MB 以下にしてください")
    sha256 = hashlib.sha256(raw).hexdigest()
    store: DocumentStore = request.app.state.documents
    status = 200
    if (doc := store.find(x_user_id, sha256)) is None:
        try:
            pages, texts = await anyio.to_thread.run_sync(inspect_pdf, raw)
        except Rejected as e:
            return error(request, e.status, e.type, e.message)
        doc, status = store.add(x_user_id, sha256, pages, raw, texts), 201
    return JSONResponse({"document_id": doc.document_id, "pages": doc.pages, "sha256": doc.sha256}, status_code=status)


def grounded(text: str, doc: StoredDocument) -> DocumentAnswer | None:
    try:
        answer = DocumentAnswer.model_validate_json(text)
    except ValidationError:
        return None
    if not answer.citations or not all(quote_exists(doc.page_texts, c.page, c.quote) for c in answer.citations):
        return None
    return answer


@app.post("/api/documents/{document_id}/ask")
async def ask_document(request: Request, document_id: str, body: AskIn, llm: Llm,
                       x_user_id: UserId = "u001") -> JSONResponse:
    s = request.app.state
    doc = s.documents.get(x_user_id, document_id)
    if doc is None:
        return error(request, 404, "not_found", MSG_NOT_FOUND)
    pages = list(range(1, doc.pages + 1))  # 本章の ask は全ページを送る（ページの選び方はセッション6）
    key = cache_key(scope=x_user_id, kind="document_ask", content_sha256=doc.sha256, preprocess={"pages": pages},
                    prompt=body.question, system=SYSTEM_PROMPT, model=settings.llm_model, schema=ANSWER_SCHEMA)
    if (hit := s.cache.get(key)) is not None:
        s.usage.count_lookup(x_user_id, hit=True)
        return JSONResponse({**hit.value, "usage": ZERO_ASK_USAGE}, headers={"x-cache": "hit"})
    s.usage.count_lookup(x_user_id, hit=False)

    req = ChatRequest(
        messages=[{"role": "user", "content": [cached(pdf_block(doc.data)), {"type": "text", "text": body.question}]}],
        system=SYSTEM_PROMPT, output_schema=ANSWER_SCHEMA, max_tokens=settings.llm_max_tokens,
    )
    used: list[Usage] = []
    answer = None
    try:
        for _ in range(MAX_ATTEMPTS):
            result = await llm.complete(req)
            used.append(result.usage)
            if (answer := grounded(result.text, doc)) is not None:
                break
    except anthropic.APIError:
        return error(request, 503, "upstream_unavailable", MSG_DOC_UPSTREAM)
    finally:
        record_llm(request, x_user_id, used)
    if answer is None:
        return error(request, 502, "invalid_output", MSG_UNGROUNDED)

    value = {"answer": answer.answer, "citations": [c.model_dump() for c in answer.citations]}
    u = total(used)
    s.cache.put(key, x_user_id, value, u)
    return JSONResponse({**value, "usage": {
        "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
        "cache_creation_input_tokens": u.cache_creation_input_tokens,
        "cache_read_input_tokens": u.cache_read_input_tokens,
    }}, headers={"x-cache": "miss"})


# ---------------------------------------------------------------- 音声（同時実行数と待ち行列）

@app.post("/api/voice/transcribe")
async def transcribe(request: Request, audio: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await audio.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", f"ファイルは {settings.upload_max_bytes // (1024 * 1024)}MB 以下にしてください")
    try:
        samples = await anyio.to_thread.run_sync(decode_wav, raw)
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


@app.post("/api/voice/speak")
async def speak(request: Request, body: SpeakIn, x_user_id: UserId = "u001") -> Response:
    s = request.app.state
    vv = s.voicevox
    try:
        await vv.ensure_user_dict()
        res = await s.tts_gate.run(vv.synthesize, body.text, sample_rate=OUTPUT_RATE)
    except Busy:
        return busy(request, "tts_busy", MSG_TTS_BUSY)
    except httpx2.HTTPError:
        return error(request, 503, "tts_unavailable", MSG_TTS_UNAVAILABLE)
    s.usage.add_audio(x_user_id, "tts", f"voicevox:{vv.speaker}", res.audio_seconds,
                      res.processing_seconds, request.state.request_id)
    return Response(res.wav, media_type="audio/wav", headers={"x-voice-credit": CREDIT_HEADER})


# ---------------------------------------------------------------- 利用量

@app.get("/api/usage")
async def usage(request: Request, x_user_id: UserId = "u001") -> dict:
    return request.app.state.usage.summary(x_user_id)
