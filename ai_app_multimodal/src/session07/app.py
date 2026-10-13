"""セッション7：レシートの取り込み（POST /api/receipts/import）。

multipart の file（画像か PDF）を受け付け、受付検査 → 二重取り込みの確認（SHA256）→ LLM で読み取り
→ 整合性検査（＋ PDF なら pypdf の文字と突き合わせ）→ 要確認の印付け、の順に処理する。
応答：{receipt_id, source, store, purchased_at, items:[{name, quantity, price}], total,
       needs_review, issues:[{index, name, reason, message}], text_checked, usage}

起動：APP_MODULE=src.session07.app:app docker compose up -d --wait api
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated

import anyio
from anthropic import AsyncAnthropic
from fastapi import FastAPI, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ulid import ULID

from kondate import __version__
from kondate.clock import SystemClock
from kondate.llm import AnthropicProvider
from kondate.settings import get_settings
from src.session07.checks import check_receipt
from src.session07.intake import MSG_TOO_LARGE, Rejected, accept_receipt
from src.session07.models import ReceiptRead
from src.session07.pdftext import ReceiptText, compare_with_text, parse_receipt_text
from src.session07.read import InvalidOutput, UpstreamUnavailable, read_receipt

settings = get_settings()

# ---- 本章で決めた値 ----
MSG_INVALID_OUTPUT = "読み取り結果の形式が正しくありませんでした"
MSG_UPSTREAM = "レシートの読み取りに失敗しました。時間をおいて試してください"
MSG_DUPLICATE = "このレシートはすでに取り込み済みです"

UserId = Annotated[str, Header(alias="x-user-id", pattern=r"^u\d{3}$")]  # 認証は①に任せ、ヘッダで代用する


# ---------------------------------------------------------------- 取り込んだレシートの置き場所

@dataclass
class StoredReceipt:
    receipt_id: str
    user_id: str
    sha256: str
    source: str                   # "image" か "pdf"
    read: ReceiptRead
    issues: list[dict]
    text: ReceiptText | None = field(default=None, repr=False)  # PDF の文字（突き合わせに使った値）
    confirmed: bool = False       # 利用者が確かめ終えたか（練習問題5で使う）

    def view(self) -> dict:
        return {
            "receipt_id": self.receipt_id,
            "source": self.source,
            **self.read.model_dump(),
            "needs_review": bool(self.issues),
            "issues": self.issues,
            "text_checked": self.text is not None,
        }


class ReceiptStore:
    """取り込んだレシートをメモリに持つ（本章の簡易版。プロセスを再起動すると消える）。"""

    def __init__(self) -> None:
        self._by_id: dict[str, StoredReceipt] = {}
        self._by_hash: dict[tuple[str, str], str] = {}  # (利用者, SHA256) → receipt_id

    def find(self, user_id: str, sha256: str) -> StoredReceipt | None:
        receipt_id = self._by_hash.get((user_id, sha256))
        return self._by_id[receipt_id] if receipt_id else None

    def add(self, receipt: StoredReceipt) -> bool:
        """入れられたら True。同じ利用者×同じ SHA256 がもうあれば False。中に await が無いので割り込まれない。"""
        key = (receipt.user_id, receipt.sha256)
        if key in self._by_hash:
            return False
        self._by_id[receipt.receipt_id] = receipt
        self._by_hash[key] = receipt.receipt_id
        return True

    def get(self, user_id: str, receipt_id: str) -> StoredReceipt | None:
        receipt = self._by_id.get(receipt_id)
        return receipt if receipt is not None and receipt.user_id == user_id else None  # 他人のものは「無い」扱い

    def of_user(self, user_id: str) -> list[StoredReceipt]:
        return [r for r in self._by_id.values() if r.user_id == user_id]


def review(read: ReceiptRead, text: ReceiptText | None, today: date) -> list[dict]:
    """整合性検査と、PDF の文字との突き合わせ。画像・文字の無い PDF は突き合わせを飛ばす。"""
    issues = check_receipt(read, today)
    if text is not None:
        issues += compare_with_text(read, text)
    return issues


# ---------------------------------------------------------------- アプリ

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = AsyncAnthropic()  # 接続先とキーは環境変数 ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む
    app.state.llm = AnthropicProvider(client)
    yield
    await client.close()


app = FastAPI(title="こんだてAI セッション7：レシートの取り込み", version=__version__, lifespan=lifespan)
app.state.receipts = ReceiptStore()
app.state.clock = SystemClock()  # 「未来の日付」の判定に使う。verify では FixedClock に差し替える


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


app.add_exception_handler(RequestValidationError, on_validation_error)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/api/receipts/import")
async def import_receipt(request: Request, file: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await file.read(settings.upload_max_bytes + 1)  # 上限より1バイトだけ多く読む
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_TOO_LARGE)

    sha256 = hashlib.sha256(raw).hexdigest()
    store: ReceiptStore = request.app.state.receipts
    if store.find(x_user_id, sha256) is not None:
        return error(request, 409, "duplicate", MSG_DUPLICATE)  # LLM を呼ぶ前に断る（料金がかからない）

    try:
        accepted = await anyio.to_thread.run_sync(accept_receipt, raw)  # Pillow・pypdf は同期処理
    except Rejected as e:
        return error(request, e.status, e.type, e.message)

    try:
        result = await read_receipt(request.app.state.llm, accepted.kind, accepted.data)
    except UpstreamUnavailable:
        return error(request, 503, "upstream_unavailable", MSG_UPSTREAM)
    except InvalidOutput:
        return error(request, 502, "invalid_output", MSG_INVALID_OUTPUT)

    text = parse_receipt_text(accepted.pdf_text)  # 画像・文字の無い PDF は None
    today = request.app.state.clock.now().date()
    receipt = StoredReceipt(
        f"rcp_{ULID()}", x_user_id, sha256, accepted.kind, result.receipt, review(result.receipt, text, today), text,
    )
    if not store.add(receipt):  # 読み取っている間に、同じレシートが別のリクエストで取り込まれた
        return error(request, 409, "duplicate", MSG_DUPLICATE)
    usage = {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens}
    return JSONResponse({**receipt.view(), "usage": usage}, status_code=201)
