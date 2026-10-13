"""中間プロジェクト1：写真と PDF からの食材・レシピ取り込み。

各セッションで作ったエンドポイント（パス・応答の形・固定文・status はそのまま）：
- POST /api/fridge/scan                     冷蔵庫の写真 → 食材リスト（セッション4）。利用者ごとに最新の1回分を在庫に使う
- POST /api/receipts/import                 レシートの画像か PDF（セッション7）
- POST /api/documents                       レシピ本の PDF の登録（セッション5）
- POST /api/documents/{id}/import-recipes   取り込みジョブ（セッション6）。成功したらレシピ本の目録に載せる
- GET /api/jobs/{id}・GET /api/jobs/{id}/events（SSE）・DELETE /api/jobs/{id}（セッション6）
中間プロジェクトで足したもの：
- GET /api/pantry           いま家にある食材（確認済みの items と、要確認の to_review）
- GET /api/pantry/recipes   確認済みの食材で search_recipes（scope=books なら取り込んだレシピ本に載っているものだけ）
LLM を呼んだら、使えなかった試行の分も含めて app.state.usage（UsageLog）に記録する。

起動：APP_MODULE=src.mid01.app:app docker compose up -d --wait api
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import anyio
from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from ulid import ULID

from kondate import __version__
from kondate.clock import Clock, SystemClock
from kondate.jobs import Job, JobQueue
from kondate.llm import AnthropicProvider, Usage
from kondate.settings import get_settings
from kondate.sse import event
from kondate.usage import UsageLog
from src.mid01 import fridge, receipt
from src.mid01.importer import import_recipes, import_total
from src.mid01.intake import MSG_FILE_TOO_LARGE, MSG_IMAGE_TOO_LARGE, Rejected, accept_image, accept_pdf, accept_receipt
from src.mid01.pantry import FridgeSnapshot, compose, find_recipes, fridge_entries, receipt_entries
from src.mid01.pdftext import compare_with_text, parse_receipt_text
from src.mid01.recipes import MAX_INGREDIENTS
from src.mid01.stores import DocumentStore, ReceiptStore, StoredReceipt

settings = get_settings()

MSG_DOC_NOT_FOUND = "文書が見つかりません"                                     # セッション5
MSG_DOC_UPSTREAM = "文書の読み取りに失敗しました。時間をおいて試してください"  # セッション5・6
MSG_JOB_NOT_FOUND = "ジョブが見つかりません"                                   # セッション6

UserId = Annotated[str, Header(alias="x-user-id", pattern=r"^u\d{3}$")]  # 認証は①に任せ、ヘッダで代用する


class JobNotFound(Exception):
    pass


def reset_state(app: FastAPI, clock: Clock | None = None) -> None:
    """利用者ごとの状態をすべて作り直す（プロセス内メモリ。再起動すると消える）。verify は検査ごとに呼ぶ。"""
    s = app.state
    s.clock = clock or SystemClock()  # レシートの「未来の日付」と利用量の時刻に使う
    s.usage = UsageLog(s.clock)       # LLM の利用量（kind="llm"）
    s.documents = DocumentStore()     # レシピ本の PDF
    s.receipts = ReceiptStore()       # 取り込んだレシート
    s.fridge = {}                     # 利用者 → 最新の冷蔵庫の写真の読み取り（FridgeSnapshot）
    s.books = {}                      # 利用者 → {document_id: 取り込んだレシピの一覧}（成功したジョブだけ）
    s.jobs = JobQueue(concurrency=1)  # 取り込みは同時に1件まで
    s.job_owners = {}                 # job_id → 利用者


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = AsyncAnthropic()  # 接続先とキーは環境変数 ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む
    app.state.llm = AnthropicProvider(client)
    yield
    await client.close()


app = FastAPI(title="こんだてAI 中間プロジェクト1：写真と PDF からの食材・レシピ取り込み",
              version=__version__, lifespan=lifespan)
reset_state(app)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = f"req_{ULID()}"
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


def error(request: Request, status: int, type_: str, message: str) -> JSONResponse:
    # 上流（Pillow・pypdf・LLM）の生のエラー文は返さない。日本語の固定文と request_id だけを返す
    return JSONResponse(
        {"error": {"type": type_, "message": message, "request_id": request.state.request_id}},
        status_code=status,
    )


async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    names = dict.fromkeys(str(e["loc"][-1]) for e in exc.errors())
    return error(request, 422, "invalid_request", f"入力値が正しくありません：{'、'.join(names)}")


async def on_job_not_found(request: Request, exc: JobNotFound) -> JSONResponse:
    return error(request, 404, "not_found", MSG_JOB_NOT_FOUND)


app.add_exception_handler(RequestValidationError, on_validation_error)
app.add_exception_handler(JobNotFound, on_job_not_found)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


def record_llm(log: UsageLog, user_id: str, used: list[Usage], request_id: str | None) -> None:
    """LLM の利用量を1件にまとめて記録する。使えなかった応答にも料金はかかるので、失敗したときも呼ぶ。"""
    input_tokens = sum(u.input_tokens for u in used)
    output_tokens = sum(u.output_tokens for u in used)
    if input_tokens or output_tokens:
        log.add(user_id, "llm", settings.llm_model,
                input_tokens=input_tokens, output_tokens=output_tokens, request_id=request_id)


async def read_capped(file: UploadFile) -> bytes | None:
    """上限より1バイトだけ多く読む。上限を超えていれば None（セッション2）。"""
    raw = await file.read(settings.upload_max_bytes + 1)
    return None if len(raw) > settings.upload_max_bytes else raw


# ---------------------------------------------------------------- 冷蔵庫の写真（セッション4）

@app.post("/api/fridge/scan")
async def fridge_scan(request: Request, image: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    if (raw := await read_capped(image)) is None:
        return error(request, 413, "too_large", MSG_IMAGE_TOO_LARGE)
    try:
        prepared = await anyio.to_thread.run_sync(accept_image, raw)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)

    state, rid = request.app.state, request.state.request_id
    try:
        result = await fridge.scan_fridge(state.llm, prepared.data)
    except fridge.UpstreamUnavailable:
        return error(request, 503, "upstream_unavailable", fridge.MSG_UPSTREAM)
    except fridge.InvalidOutput as e:
        record_llm(state.usage, x_user_id, [e.usage], rid)  # 在庫は前の写真のまま
        return error(request, 502, "invalid_output", fridge.MSG_INVALID_OUTPUT)
    record_llm(state.usage, x_user_id, [result.usage], rid)

    issues = fridge.find_issues(result.scan.ingredients)
    state.fridge[x_user_id] = FridgeSnapshot(result.scan.ingredients, issues)  # 撮り直したら置き換える
    return JSONResponse({
        "ingredients": [i.model_dump() for i in result.scan.ingredients],
        "needs_review": bool(issues),
        "issues": issues,
        "image": prepared.info(),
        "usage": {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens},
    })


# ---------------------------------------------------------------- レシート（セッション7）

@app.post("/api/receipts/import")
async def import_receipt(request: Request, file: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    if (raw := await read_capped(file)) is None:
        return error(request, 413, "too_large", MSG_FILE_TOO_LARGE)
    sha256 = hashlib.sha256(raw).hexdigest()
    state, rid = request.app.state, request.state.request_id
    store: ReceiptStore = state.receipts
    if store.find(x_user_id, sha256) is not None:
        return error(request, 409, "duplicate", receipt.MSG_DUPLICATE)  # LLM を呼ぶ前に断る
    try:
        accepted = await anyio.to_thread.run_sync(accept_receipt, raw)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)

    try:
        result = await receipt.read_receipt(state.llm, accepted.kind, accepted.data)
    except receipt.UpstreamUnavailable:
        return error(request, 503, "upstream_unavailable", receipt.MSG_UPSTREAM)
    except receipt.InvalidOutput as e:
        record_llm(state.usage, x_user_id, [e.usage], rid)
        return error(request, 502, "invalid_output", receipt.MSG_INVALID_OUTPUT)
    record_llm(state.usage, x_user_id, [result.usage], rid)

    text = parse_receipt_text(accepted.pdf_text)  # 画像・文字の無い PDF は None
    issues = receipt.check_receipt(result.receipt, state.clock.now().date())
    if text is not None:
        issues += compare_with_text(result.receipt, text)
    stored = StoredReceipt(f"rcp_{ULID()}", x_user_id, sha256, accepted.kind, result.receipt, issues, text)
    if not store.add(stored):
        return error(request, 409, "duplicate", receipt.MSG_DUPLICATE)
    usage = {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens}
    return JSONResponse({**stored.view(), "usage": usage}, status_code=201)


# ---------------------------------------------------------------- レシピ本（セッション5・6）

@app.post("/api/documents")
async def create_document(request: Request, file: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    if (raw := await read_capped(file)) is None:
        return error(request, 413, "too_large", MSG_FILE_TOO_LARGE)
    sha256 = hashlib.sha256(raw).hexdigest()
    store: DocumentStore = request.app.state.documents
    if (doc := store.find(x_user_id, sha256)) is not None:
        return JSONResponse(doc.view(), status_code=200)  # 同じ内容は調べ直さず、同じ ID を返す
    try:
        pages = await anyio.to_thread.run_sync(accept_pdf, raw)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)
    doc, created = store.add(x_user_id, sha256, pages, raw)
    return JSONResponse(doc.view(), status_code=201 if created else 200)


@app.post("/api/documents/{document_id}/import-recipes", status_code=202)
async def start_import(request: Request, document_id: str, x_user_id: UserId = "u001") -> JSONResponse:
    state, rid = request.app.state, request.state.request_id
    doc = state.documents.get(x_user_id, document_id)
    if doc is None:
        return error(request, 404, "not_found", MSG_DOC_NOT_FOUND)
    llm = state.llm

    async def work(progress) -> dict:
        used: list[Usage] = []
        try:
            result = await import_recipes(llm, doc.data, doc.pages, progress, used)
        finally:
            record_llm(state.usage, x_user_id, used, rid)  # 取り消し・失敗でも、そこまでに使った分は記録する
        state.books.setdefault(x_user_id, {})[doc.document_id] = result["recipes"]  # 成功したときだけ目録に載せる
        return {"document_id": doc.document_id, **result}

    job = state.jobs.submit(work, total=import_total(doc.pages))
    state.job_owners[job.id] = x_user_id
    return JSONResponse({"job_id": job.id}, status_code=202)


async def owned_job(request: Request, job_id: str, x_user_id: UserId = "u001") -> Job:
    """自分のジョブだけを返す。他人のジョブも、無いジョブも、同じ 404 にする（存在を教えない）。"""
    job = request.app.state.jobs.get(job_id)
    if job is None or request.app.state.job_owners.get(job_id) != x_user_id:
        raise JobNotFound()
    return job


OwnedJob = Annotated[Job, Depends(owned_job)]


@app.get("/api/jobs/{job_id}")
async def get_job(job: OwnedJob) -> dict:
    return {**job.snapshot(), "result": job.result}


@app.get("/api/jobs/{job_id}/events", response_class=EventSourceResponse)
async def job_events(request: Request, job: OwnedJob) -> AsyncIterator[ServerSentEvent]:
    async for snap in request.app.state.jobs.events(job.id):
        yield event("progress", snap)
    if job.status == "succeeded":
        yield event("done", {"result": job.result})
    elif job.status == "failed":
        yield event("error", {"type": "upstream_unavailable", "message": MSG_DOC_UPSTREAM,
                              "request_id": request.state.request_id})


@app.delete("/api/jobs/{job_id}")
async def cancel_job(request: Request, job: OwnedJob) -> dict:
    queue: JobQueue = request.app.state.jobs
    if queue.cancel(job.id):
        async for _ in queue.events(job.id):
            pass
    return job.snapshot()


# ---------------------------------------------------------------- 在庫と作れるレシピ（中間プロジェクト1で足したもの）

def pantry_of(state, user_id: str) -> dict:
    """冷蔵庫の写真（最新の1回分）とレシート（すべて）から、その利用者の在庫を組み立てる。"""
    entries = []
    if (snap := state.fridge.get(user_id)) is not None:
        entries += fridge_entries(snap)
    for r in state.receipts.of_user(user_id):
        entries += receipt_entries(r.receipt_id, r.read.items, r.issues)
    return compose(entries)


@app.get("/api/pantry")
async def get_pantry(request: Request, x_user_id: UserId = "u001") -> dict:
    return pantry_of(request.app.state, x_user_id)


@app.get("/api/pantry/recipes")
async def pantry_recipes(
    request: Request,
    scope: Literal["all", "books"] = "all",
    max_minutes: Annotated[int | None, Query(ge=1, le=240)] = None,
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
    x_user_id: UserId = "u001",
) -> dict:
    state = request.app.state
    pantry = pantry_of(state, x_user_id)
    names = [i["name"] for i in pantry["items"]][:MAX_INGREDIENTS]
    found = find_recipes(names, state.books.get(x_user_id, {}), scope, max_minutes, limit)
    return {"ingredients": names, "scope": scope, "recipes": found, "to_review_count": len(pantry["to_review"])}
