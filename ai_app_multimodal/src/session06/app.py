"""セッション6：大きな文書 ― ページ選択・分割・キャッシュ。

- POST /api/documents                       PDF の登録（セッション5と同じ。登録時に見出しの索引を作る）
- POST /api/documents/{id}/ask              pages（1始まり）で読むページを選ぶ。document ブロックにキャッシュの印を付ける
- POST /api/documents/{id}/import-recipes   202 {job_id}。全ページを10ページずつ（1ページ重ねて）読み、ID で統合する
- GET /api/jobs/{job_id}・GET /api/jobs/{job_id}/events（SSE）・DELETE /api/jobs/{job_id}

起動：APP_MODULE=src.session06.app:app docker compose up -d --wait api
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated

import anthropic
import anyio
from anthropic import AsyncAnthropic, transform_schema
from fastapi import Depends, FastAPI, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field, ValidationError
from pypdf import PdfReader
from ulid import ULID

from kondate import __version__
from kondate.jobs import Job, JobQueue
from kondate.llm import AnthropicProvider, ChatRequest, LLMProvider, Usage
from kondate.settings import get_settings
from kondate.sse import event
from src.session06.documents import cached, check_citation, extract_pages, pdf_block
from src.session06.importer import import_recipes, import_total
from src.session06.pages import APP_MAX_PAGES, ASK_MAX_PAGES, Heading, build_index, guess_pages, select_pages

settings = get_settings()

# ---- 受付の値（セッション2・5と同じ） ----
MSG_TOO_LARGE = f"ファイルは {settings.upload_max_bytes // (1024 * 1024)}MB 以下にしてください"
MSG_TOO_MANY_PAGES = f"PDF は {APP_MAX_PAGES} ページ以下にしてください"
MSG_NOT_PDF = "PDF を送ってください"
MSG_NOT_FOUND = "文書が見つかりません"
MSG_UPSTREAM = "文書の読み取りに失敗しました。時間をおいて試してください"
MSG_UNGROUNDED = "回答の根拠を文書の中で確かめられませんでした"
MAX_ATTEMPTS = 2
SYSTEM_PROMPT = (
    "添付の文書だけを根拠に答えてください。"
    "根拠にした文は文書から一字一句そのまま写し、ページ番号（1始まり）と一緒に引用として示してください。"
)

# ---- 本章で決めた値 ----
MSG_PAGES_COUNT = f"pages は 1〜{ASK_MAX_PAGES} 個で指定してください"
MSG_PAGES_REQUIRED = "読むページを決められませんでした。pages でページ番号を指定してください"
MSG_JOB_NOT_FOUND = "ジョブが見つかりません"
SELECTION_CACHE_SIZE = 8  # 文書ごとに覚えておく「選んだページの PDF」の数

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
    pages: list[int] | None = None  # 読むページ（1始まり）。省略すると、小さな文書は全ページ・大きな文書は索引で当たりを付ける


# ---------------------------------------------------------------- 受付（セッション5と同じ）

class Rejected(Exception):
    def __init__(self, status: int, type_: str, message: str) -> None:
        super().__init__(message)
        self.status, self.type, self.message = status, type_, message


class JobNotFound(Exception):
    pass


def inspect_pdf(raw: bytes) -> tuple[int, list[str]]:
    """中身で PDF かどうかを確かめ、(ページ数, ページごとの抽出テキスト) を返す。"""
    if not raw.startswith(b"%PDF-"):
        raise Rejected(415, "unsupported_media", MSG_NOT_PDF)
    try:
        pages = len(PdfReader(io.BytesIO(raw)).pages)
    except Exception:  # 壊れた PDF に pypdf はさまざまな例外を投げる。種類を問わず「開けない」と扱う
        raise Rejected(415, "unsupported_media", MSG_NOT_PDF) from None
    if pages == 0:
        raise Rejected(415, "unsupported_media", MSG_NOT_PDF)
    if pages > APP_MAX_PAGES:
        raise Rejected(413, "too_large", MSG_TOO_MANY_PAGES)
    try:
        texts = extract_pages(raw)
    except Exception:
        texts = [""] * pages
    return pages, texts


# ---------------------------------------------------------------- 文書の置き場所

@dataclass
class StoredDocument:
    document_id: str
    user_id: str
    sha256: str
    pages: int
    data: bytes = field(repr=False)
    page_texts: list[str] = field(repr=False)
    index: list[Heading] = field(repr=False)  # 見出しの索引（目次の代わり）
    selections: dict[tuple[int, ...], bytes] = field(default_factory=dict, repr=False)


class DocumentStore:
    """登録した文書をメモリに持つ（プロセスを再起動すると消える）。"""

    def __init__(self) -> None:
        self._by_id: dict[str, StoredDocument] = {}
        self._by_hash: dict[tuple[str, str], str] = {}

    def find(self, user_id: str, sha256: str) -> StoredDocument | None:
        doc_id = self._by_hash.get((user_id, sha256))
        return self._by_id[doc_id] if doc_id else None

    def add(self, user_id: str, sha256: str, pages: int, data: bytes, texts: list[str]) -> tuple[StoredDocument, bool]:
        if (existing := self.find(user_id, sha256)) is not None:
            return existing, False
        doc = StoredDocument(f"doc_{ULID()}", user_id, sha256, pages, data, texts, build_index(texts))
        self._by_id[doc.document_id] = doc
        self._by_hash[(user_id, sha256)] = doc.document_id
        return doc, True

    def get(self, user_id: str, document_id: str) -> StoredDocument | None:
        doc = self._by_id.get(document_id)
        return doc if doc is not None and doc.user_id == user_id else None


# ---------------------------------------------------------------- アプリ

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = AsyncAnthropic()  # 接続先とキーは環境変数 ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む
    app.state.llm = AnthropicProvider(client)
    yield
    await client.close()


app = FastAPI(title="こんだてAI セッション6：大きな文書", version=__version__, lifespan=lifespan)
app.state.documents = DocumentStore()
app.state.jobs = JobQueue(concurrency=1)  # 取り込みは同時に1件まで（プロセス内の最小版）
app.state.job_owners = {}                 # job_id → 利用者


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
    names = dict.fromkeys(str(e["loc"][-1]) for e in exc.errors())
    return error(request, 422, "invalid_request", f"入力値が正しくありません：{'、'.join(names)}")


async def on_job_not_found(request: Request, exc: JobNotFound) -> JSONResponse:
    return error(request, 404, "not_found", MSG_JOB_NOT_FOUND)


app.add_exception_handler(RequestValidationError, on_validation_error)
app.add_exception_handler(JobNotFound, on_job_not_found)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


def document_view(doc: StoredDocument) -> dict:
    return {"document_id": doc.document_id, "pages": doc.pages, "sha256": doc.sha256}


@app.post("/api/documents")
async def create_document(request: Request, file: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await file.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_TOO_LARGE)
    sha256 = hashlib.sha256(raw).hexdigest()
    store: DocumentStore = request.app.state.documents
    if (doc := store.find(x_user_id, sha256)) is not None:
        return JSONResponse(document_view(doc), status_code=200)
    try:
        pages, texts = await anyio.to_thread.run_sync(inspect_pdf, raw)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)
    doc, created = store.add(x_user_id, sha256, pages, raw, texts)
    return JSONResponse(document_view(doc), status_code=201 if created else 200)


# ---------------------------------------------------------------- ask：ページを選んで送る

def choose_pages(doc: StoredDocument, body: AskIn) -> list[int]:
    """送るページ（元の PDF のページ番号・昇順・重複なし）を決める。"""
    if body.pages is not None:
        pages = sorted(set(body.pages))
        if not 1 <= len(pages) <= ASK_MAX_PAGES:
            raise Rejected(422, "invalid_request", MSG_PAGES_COUNT)
        if pages[0] < 1 or pages[-1] > doc.pages:
            raise Rejected(422, "invalid_request", f"pages は 1〜{doc.pages} の範囲で指定してください")
        return pages
    if doc.pages <= ASK_MAX_PAGES:
        return list(range(1, doc.pages + 1))
    pages = guess_pages(doc.index, body.question)  # 大きな文書は、見出しの索引で当たりを付ける
    if not 1 <= len(pages) <= ASK_MAX_PAGES:
        raise Rejected(422, "invalid_request", MSG_PAGES_REQUIRED)
    return pages


async def selected_pdf(doc: StoredDocument, pages: list[int]) -> bytes:
    """選んだページの PDF。同じ組み合わせには、前に作ったバイト列をそのまま返す（キャッシュの接頭辞を変えない）。"""
    if pages == list(range(1, doc.pages + 1)):
        return doc.data
    key = tuple(pages)
    if key not in doc.selections:
        doc.selections[key] = await anyio.to_thread.run_sync(select_pages, doc.data, pages)
        while len(doc.selections) > SELECTION_CACHE_SIZE:
            del doc.selections[next(iter(doc.selections))]  # 古いものから捨てる
    return doc.selections[key]


def grounded_answer(text: str, page_texts: list[str], sent: list[int]) -> DocumentAnswer | None:
    """引用のページ番号（送った PDF の中での番号）を元の番号に戻し、元のページで実在を確かめる。"""
    try:
        answer = DocumentAnswer.model_validate_json(text)
    except ValidationError:
        return None
    if not answer.citations:
        return None
    citations = []
    for c in answer.citations:
        if not 1 <= c.page <= len(sent):
            return None  # 送っていないページを引用している
        original = sent[c.page - 1]
        if not check_citation(page_texts, original, c.quote).ok:
            return None
        citations.append(Citation(page=original, quote=c.quote))
    return DocumentAnswer(answer=answer.answer, citations=citations)


def usage_view(used: list[Usage]) -> dict:
    return {
        "input_tokens": sum(u.input_tokens for u in used),  # キャッシュに乗らなかった分
        "output_tokens": sum(u.output_tokens for u in used),
        "cache_creation_input_tokens": sum(u.cache_creation_input_tokens for u in used),
        "cache_read_input_tokens": sum(u.cache_read_input_tokens for u in used),
    }


@app.post("/api/documents/{document_id}/ask")
async def ask_document(request: Request, document_id: str, body: AskIn, x_user_id: UserId = "u001") -> JSONResponse:
    doc = request.app.state.documents.get(x_user_id, document_id)
    if doc is None:
        return error(request, 404, "not_found", MSG_NOT_FOUND)
    try:
        sent = choose_pages(doc, body)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)
    data = await selected_pdf(doc, sent)
    req = ChatRequest(
        messages=[{"role": "user", "content": [cached(pdf_block(data)), {"type": "text", "text": body.question}]}],
        system=SYSTEM_PROMPT,
        output_schema=ANSWER_SCHEMA,
        max_tokens=settings.llm_max_tokens,
    )
    llm: LLMProvider = request.app.state.llm
    used: list[Usage] = []
    for _ in range(MAX_ATTEMPTS):
        try:
            result = await llm.complete(req)
        except anthropic.APIError:
            return error(request, 503, "upstream_unavailable", MSG_UPSTREAM)
        used.append(result.usage)
        answer = grounded_answer(result.text, doc.page_texts, sent)
        if answer is not None:
            return JSONResponse({
                "answer": answer.answer,
                "citations": [c.model_dump() for c in answer.citations],
                "usage": usage_view(used),
            })
    return error(request, 502, "invalid_output", MSG_UNGROUNDED)


# ---------------------------------------------------------------- 取り込みジョブ

@app.post("/api/documents/{document_id}/import-recipes", status_code=202)
async def start_import(request: Request, document_id: str, x_user_id: UserId = "u001") -> JSONResponse:
    doc = request.app.state.documents.get(x_user_id, document_id)
    if doc is None:
        return error(request, 404, "not_found", MSG_NOT_FOUND)
    llm: LLMProvider = request.app.state.llm

    async def work(progress) -> dict:
        result = await import_recipes(llm, doc.data, doc.pages, progress)
        return {"document_id": doc.document_id, **result}

    job = request.app.state.jobs.submit(work, total=import_total(doc.pages))
    request.app.state.job_owners[job.id] = x_user_id
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
        yield event("progress", snap)  # {job_id, status, done, total}
    if job.status == "succeeded":
        yield event("done", {"result": job.result})
    elif job.status == "failed":
        yield event("error", {"type": "upstream_unavailable", "message": MSG_UPSTREAM,
                              "request_id": request.state.request_id})
    # cancelled は、status が cancelled の progress で終わる（途中までの結果は捨てる）


@app.delete("/api/jobs/{job_id}")
async def cancel_job(request: Request, job: OwnedJob) -> dict:
    queue: JobQueue = request.app.state.jobs
    if queue.cancel(job.id):
        async for _ in queue.events(job.id):  # 取り消しが反映される（status が cancelled になる）まで待つ
            pass
    return job.snapshot()
