"""レシートの読み取りと、取り込んだレシートの形（セッション7の read.py・app.py から必要な分を写したもの）。

read_receipt は scan.py と同じく「used に足していく」書き方にそろえた（セッション14）。
取り込んだレシートは台帳（privacy.PersonalStore）に種別 receipt（30日）として載せる。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import date

from pydantic import ValidationError

from kondate.llm import ChatRequest, LLMProvider, Usage
from kondate.settings import get_settings
from src.final.checks import check_receipt
from src.final.models import RECEIPT_SCHEMA, ReceiptRead
from src.final.pdftext import ReceiptText, compare_with_text

RECEIPT_PROMPT = "このレシートを読み取ってください。購入日はYYYY-MM-DDの形式、金額は円の整数で書いてください。"
MAX_ATTEMPTS = 2


def receipt_block(kind: str, data: bytes) -> dict:
    b64 = base64.standard_b64encode(data).decode("ascii")
    if kind == "image":
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}


def build_request(kind: str, data: bytes) -> ChatRequest:
    return ChatRequest(
        messages=[{"role": "user", "content": [receipt_block(kind, data), {"type": "text", "text": RECEIPT_PROMPT}]}],
        output_schema=RECEIPT_SCHEMA,
        max_tokens=get_settings().llm_max_tokens,
    )


async def read_receipt(llm: LLMProvider, kind: str, data: bytes, used: list[Usage]) -> ReceiptRead | None:
    req = build_request(kind, data)
    for _ in range(MAX_ATTEMPTS):
        result = await llm.complete(req)
        used.append(result.usage)
        if result.stop_reason == "max_tokens":
            return None
        try:
            return ReceiptRead.model_validate_json(result.text)
        except ValidationError:
            continue
    return None


def review(read: ReceiptRead, text: ReceiptText | None, today: date) -> list[dict]:
    issues = check_receipt(read, today)
    if text is not None:
        issues += compare_with_text(read, text)
    return issues


@dataclass
class StoredReceipt:
    receipt_id: str
    user_id: str
    sha256: str
    source: str                                  # "image" か "pdf"
    read: ReceiptRead
    issues: list[dict]
    text_checked: bool
    pantry: tuple[str, ...] = field(default=())  # 最終：声の相談に添える食材名（食材辞書の語だけ）

    def view(self) -> dict:
        return {
            "receipt_id": self.receipt_id,
            "source": self.source,
            **self.read.model_dump(),
            "needs_review": bool(self.issues),
            "issues": self.issues,
            "text_checked": self.text_checked,
        }
