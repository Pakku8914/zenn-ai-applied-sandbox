"""評価対象②：レシート（画像か PDF）→ 購入品（セッション7のコードから、評価に要る部分だけを写したもの）。

画像は image ブロック、PDF は document ブロックで送り、どちらも同じスキーマ（ReceiptRead）で受け取って再検証する。
そのあと整合性検査（日付・合計・金額の範囲）で要確認の印を付ける。pypdf の文字との突き合わせは写していない。
"""

from __future__ import annotations

import base64
import io
import re
from datetime import date
from typing import Annotated

import anthropic
from anthropic import transform_schema
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from pypdf import PdfReader

from kondate.llm import ChatRequest, LLMProvider
from kondate.settings import get_settings
from src.session12.target_fridge import InvalidOutput, UpstreamUnavailable, prepare_image

RECEIPT_PROMPT = "このレシートを読み取ってください。購入日はYYYY-MM-DDの形式、金額は円の整数で書いてください。"
MAX_ATTEMPTS = 2
MAX_PDF_PAGES = 200
PRICE_MIN, PRICE_MAX = 1, 100_000
DATE_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}$")

__all__ = ["InvalidOutput", "UpstreamUnavailable", "accept_receipt", "read_receipt", "check_receipt"]

Text40 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class ReceiptItem(BaseModel):
    name: Text40 = Field(description="品名（レシートの表記のまま）")
    quantity: int = Field(description="個数（書かれていなければ1）")
    price: int = Field(description="その行の金額（円の整数。個数を掛けたあとの額）")


class ReceiptRead(BaseModel):
    store: Text40 = Field(description="店名")
    purchased_at: str = Field(description="購入日（YYYY-MM-DD）")
    items: list[ReceiptItem] = Field(min_length=1, description="購入品（レシートの上から順に）")
    total: int = Field(description="合計金額（円の整数）")


RECEIPT_SCHEMA = transform_schema(ReceiptRead)


def accept_receipt(raw: bytes) -> tuple[str, bytes]:
    """("pdf", 受け取ったまま) か ("image", 作り直した JPEG)。評価に使うのは検証用の画像・PDF だけなので、形式の判定は簡略にしてある。"""
    if raw.startswith(b"%PDF-"):
        pages = len(PdfReader(io.BytesIO(raw)).pages)
        if not 1 <= pages <= MAX_PDF_PAGES:
            raise ValueError(f"PDF のページ数が範囲外です（{pages}）")
        return "pdf", raw
    return "image", prepare_image(raw)


def build_request(kind: str, data: bytes) -> ChatRequest:
    b64 = base64.standard_b64encode(data).decode("ascii")
    if kind == "image":
        block = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}
    else:
        block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    return ChatRequest(
        messages=[{"role": "user", "content": [block, {"type": "text", "text": RECEIPT_PROMPT}]}],
        output_schema=RECEIPT_SCHEMA,
        max_tokens=get_settings().llm_max_tokens,
    )


async def read_receipt(llm: LLMProvider, kind: str, data: bytes) -> ReceiptRead:
    req = build_request(kind, data)
    for _ in range(MAX_ATTEMPTS):
        try:
            result = await llm.complete(req)
        except anthropic.APIError as e:
            raise UpstreamUnavailable() from e
        if result.stop_reason == "max_tokens":
            raise InvalidOutput("max_tokens")
        try:
            return ReceiptRead.model_validate_json(result.text)
        except ValidationError:
            continue
    raise InvalidOutput("validation")


def valid_date(value: str, today: date) -> bool:
    if not DATE_FORMAT.match(value):
        return False
    try:
        return date.fromisoformat(value) <= today
    except ValueError:
        return False


def check_receipt(read: ReceiptRead, today: date) -> list[dict]:
    """整合性検査（セッション7と同じ基準）。レシート全体の問題は index・name を None にする。"""
    issues: list[dict] = []
    if not valid_date(read.purchased_at, today):
        issues.append({"index": None, "name": None, "reason": "invalid_date"})
    if sum(item.price for item in read.items) != read.total:
        issues.append({"index": None, "name": None, "reason": "total_mismatch"})
    for index, item in enumerate(read.items):
        if not PRICE_MIN <= item.price <= PRICE_MAX:
            issues.append({"index": index, "name": item.name, "reason": "price_out_of_range"})
    return issues
