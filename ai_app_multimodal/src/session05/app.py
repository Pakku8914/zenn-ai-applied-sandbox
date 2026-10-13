"""セッション5：PDF の文書理解（POST /api/documents・POST /api/documents/{id}/ask）。

PDF を登録して doc_+ULID を振る（同じ利用者が同じ内容を送ったら同じ ID を返す）。
質問には「答え＋ページ番号＋引用文」を構造化出力で返させ、引用文が本当にそのページにあるかを
pypdf の抽出結果で確かめる。確かめられなければ1回だけ再試行し、それでも駄目なら 502 にする。

起動：APP_MODULE=src.session05.app:app docker compose up -d --wait api
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
from fastapi import FastAPI, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from pypdf import PdfReader
from ulid import ULID

from kondate import __version__
from kondate.llm import AnthropicProvider, ChatRequest, LLMProvider, Usage
from kondate.settings import get_settings
from src.session05.documents import check_citation, extract_pages, pdf_block

settings = get_settings()

# ---- 受付の値（セッション2と同じ） ----
MAX_PDF_PAGES = 200
MSG_TOO_LARGE = f"ファイルは {settings.upload_max_bytes // (1024 * 1024)}MB 以下にしてください"
MSG_TOO_MANY_PAGES = f"PDF は {MAX_PDF_PAGES} ページ以下にしてください"

# ---- 本章で決めた値 ----
MSG_NOT_PDF = "PDF を送ってください"
MSG_NOT_FOUND = "文書が見つかりません"
MSG_UPSTREAM = "文書の読み取りに失敗しました。時間をおいて試してください"
MSG_UNGROUNDED = "回答の根拠を文書の中で確かめられませんでした"
MAX_ATTEMPTS = 2  # 最初の1回＋再試行1回
SYSTEM_PROMPT = (
    "添付の文書だけを根拠に答えてください。"
    "根拠にした文は文書から一字一句そのまま写し、ページ番号（1始まり）と一緒に引用として示してください。"
)

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
    pages: list[int] | None = None  # 読むページの指定は次章で使う。本章では受け取るだけで、文書全体を送る


# ---------------------------------------------------------------- 受付（セッション2の検査を PDF だけに絞ったもの）

class Rejected(Exception):
    def __init__(self, status: int, type_: str, message: str) -> None:
        super().__init__(message)
        self.status, self.type, self.message = status, type_, message


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
    if pages > MAX_PDF_PAGES:
        raise Rejected(413, "too_large", MSG_TOO_MANY_PAGES)
    try:
        texts = extract_pages(raw)
    except Exception:  # 文字を抜き出せない PDF も登録はする（引用は確かめられないので ask は 502 になる）
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


class DocumentStore:
    """登録した文書をメモリに持つ（本章の簡易版。プロセスを再起動すると消える）。"""

    def __init__(self) -> None:
        self._by_id: dict[str, StoredDocument] = {}
        self._by_hash: dict[tuple[str, str], str] = {}  # (利用者, SHA256) → document_id

    def find(self, user_id: str, sha256: str) -> StoredDocument | None:
        doc_id = self._by_hash.get((user_id, sha256))
        return self._by_id[doc_id] if doc_id else None

    def add(self, user_id: str, sha256: str, pages: int, data: bytes, texts: list[str]) -> tuple[StoredDocument, bool]:
        """(文書, 新しく作ったか) を返す。中に await が無いので、確かめてから入れるまでに割り込まれない。"""
        if (existing := self.find(user_id, sha256)) is not None:
            return existing, False
        doc = StoredDocument(f"doc_{ULID()}", user_id, sha256, pages, data, texts)
        self._by_id[doc.document_id] = doc
        self._by_hash[(user_id, sha256)] = doc.document_id
        return doc, True

    def get(self, user_id: str, document_id: str) -> StoredDocument | None:
        doc = self._by_id.get(document_id)
        return doc if doc is not None and doc.user_id == user_id else None  # 他人の文書は「無い」と同じに扱う


# ---------------------------------------------------------------- アプリ

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = AsyncAnthropic()  # 接続先とキーは環境変数 ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む
    app.state.llm = AnthropicProvider(client)
    yield
    await client.close()


app = FastAPI(title="こんだてAI セッション5：PDF の文書理解", version=__version__, lifespan=lifespan)
app.state.documents = DocumentStore()


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = f"req_{ULID()}"
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


def error(request: Request, status: int, type_: str, message: str) -> JSONResponse:
    # 上流（pypdf・LLM）の生のエラー文は返さない。日本語の固定文と request_id だけを返す
    return JSONResponse(
        {"error": {"type": type_, "message": message, "request_id": request.state.request_id}},
        status_code=status,
    )


async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    names = dict.fromkeys(str(e["loc"][-1]) for e in exc.errors())
    return error(request, 422, "invalid_request", f"入力値が正しくありません：{'、'.join(names)}")


app.add_exception_handler(RequestValidationError, on_validation_error)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


def document_view(doc: StoredDocument) -> dict:
    return {"document_id": doc.document_id, "pages": doc.pages, "sha256": doc.sha256}


@app.post("/api/documents")
async def create_document(request: Request, file: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await file.read(settings.upload_max_bytes + 1)  # 上限より1バイトだけ多く読む
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_TOO_LARGE)
    sha256 = hashlib.sha256(raw).hexdigest()
    store: DocumentStore = request.app.state.documents
    if (doc := store.find(x_user_id, sha256)) is not None:
        return JSONResponse(document_view(doc), status_code=200)  # 同じ内容は調べ直さず、同じ ID を返す
    try:
        pages, texts = await anyio.to_thread.run_sync(inspect_pdf, raw)  # pypdf は同期処理
    except Rejected as e:
        return error(request, e.status, e.type, e.message)
    doc, created = store.add(x_user_id, sha256, pages, raw, texts)
    return JSONResponse(document_view(doc), status_code=201 if created else 200)


def grounded_answer(text: str, page_texts: list[str]) -> DocumentAnswer | None:
    """構造化出力を Pydantic で検証し、引用が1件以上あり、すべてが実在するときだけ返す。"""
    try:
        answer = DocumentAnswer.model_validate_json(text)
    except ValidationError:
        return None
    checks = [check_citation(page_texts, c.page, c.quote) for c in answer.citations]
    if not checks or not all(c.ok for c in checks):
        return None
    return answer


@app.post("/api/documents/{document_id}/ask")
async def ask_document(request: Request, document_id: str, body: AskIn, x_user_id: UserId = "u001") -> JSONResponse:
    doc = request.app.state.documents.get(x_user_id, document_id)
    if doc is None:
        return error(request, 404, "not_found", MSG_NOT_FOUND)
    req = ChatRequest(
        messages=[{"role": "user", "content": [pdf_block(doc.data), {"type": "text", "text": body.question}]}],
        system=SYSTEM_PROMPT,
        output_schema=ANSWER_SCHEMA,
        max_tokens=settings.llm_max_tokens,
    )
    llm: LLMProvider = request.app.state.llm
    used: list[Usage] = []  # 再試行の分も料金はかかるので、すべて足して返す
    for _ in range(MAX_ATTEMPTS):
        try:
            result = await llm.complete(req)
        except anthropic.APIError:
            return error(request, 503, "upstream_unavailable", MSG_UPSTREAM)
        used.append(result.usage)
        answer = grounded_answer(result.text, doc.page_texts)
        if answer is not None:
            return JSONResponse({
                "answer": answer.answer,
                "citations": [c.model_dump() for c in answer.citations],
                "usage": {
                    "input_tokens": sum(u.input_tokens for u in used),
                    "output_tokens": sum(u.output_tokens for u in used),
                },
            })
    return error(request, 502, "invalid_output", MSG_UNGROUNDED)
