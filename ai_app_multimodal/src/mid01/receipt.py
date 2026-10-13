"""レシートの読み取り（セッション7の models.py・read.py・checks.py を1つにまとめたもの。中身は同じ）。"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Annotated

import anthropic
from anthropic import transform_schema
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from kondate.llm import ChatRequest, LLMProvider, Usage
from kondate.settings import get_settings

log = logging.getLogger(__name__)

MSG_INVALID_OUTPUT = "読み取り結果の形式が正しくありませんでした"
MSG_UPSTREAM = "レシートの読み取りに失敗しました。時間をおいて試してください"
MSG_DUPLICATE = "このレシートはすでに取り込み済みです"


# ---------------------------------------------------------------- 形（models.py）

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


# ---------------------------------------------------------------- 読み取り（read.py）

RECEIPT_PROMPT = "このレシートを読み取ってください。購入日はYYYY-MM-DDの形式、金額は円の整数で書いてください。"
MAX_ATTEMPTS = 2


class UpstreamUnavailable(Exception):
    """LLM の API から応答を得られなかった（SDK の再試行も尽きた）。"""


class InvalidOutput(Exception):
    """応答はあったが、レシートの読み取り結果として使える形ではなかった。"""

    def __init__(self, reason: str, attempts: int, usage: Usage) -> None:
        super().__init__(reason)
        self.reason, self.attempts, self.usage = reason, attempts, usage


@dataclass(frozen=True)
class ReadResult:
    receipt: ReceiptRead
    attempts: int
    usage: Usage


def receipt_block(kind: str, data: bytes) -> dict:
    b64 = base64.standard_b64encode(data).decode("ascii")
    if kind == "image":
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}
    if kind == "pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    raise ValueError(f"未対応の種類です: {kind}")


def build_request(kind: str, data: bytes, max_tokens: int | None = None) -> ChatRequest:
    return ChatRequest(
        messages=[{"role": "user", "content": [receipt_block(kind, data), {"type": "text", "text": RECEIPT_PROMPT}]}],
        output_schema=RECEIPT_SCHEMA,
        max_tokens=max_tokens or get_settings().llm_max_tokens,
    )


def error_summary(e: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in err['loc']) or '(全体)'}: {err['type']}" for err in e.errors()]


async def read_receipt(llm: LLMProvider, kind: str, data: bytes, max_tokens: int | None = None) -> ReadResult:
    req = build_request(kind, data, max_tokens)
    used_in = used_out = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = await llm.complete(req)
        except anthropic.APIError as e:
            raise UpstreamUnavailable() from e
        used_in += result.usage.input_tokens
        used_out += result.usage.output_tokens
        usage = Usage(used_in, used_out)
        if result.stop_reason == "max_tokens":
            log.warning("receipt: max_tokens で打ち切られました（%d回目）", attempt)
            raise InvalidOutput("max_tokens", attempt, usage)
        try:
            return ReadResult(ReceiptRead.model_validate_json(result.text), attempt, usage)
        except ValidationError as e:
            log.warning("receipt: 検証に失敗しました（%d回目）: %s", attempt, error_summary(e))
    raise InvalidOutput("validation", MAX_ATTEMPTS, usage)


# ---------------------------------------------------------------- 整合性検査（checks.py）

PRICE_MIN = 1
PRICE_MAX = 100_000
DATE_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MESSAGES = {
    "invalid_date": "購入日が YYYY-MM-DD の形でないか、ありえない日付（存在しない日・未来の日）です。日付を確かめてください",
    "total_mismatch": "明細の金額の合計と、合計金額が一致しません。金額を確かめてください",
    "price_out_of_range": f"金額が想定の範囲（{PRICE_MIN}〜{PRICE_MAX:,}円）を外れています。金額を確かめてください",
    "text_mismatch": "PDF に書かれた文字と読み取り結果が一致しません。レシートと見比べてください",
}


def issue(index: int | None, name: str | None, reason: str) -> dict:
    return {"index": index, "name": name, "reason": reason, "message": MESSAGES[reason]}


def valid_date(value: str, today: date) -> bool:
    if not DATE_FORMAT.match(value):
        return False
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return False
    return day <= today


def check_receipt(read: ReceiptRead, today: date) -> list[dict]:
    issues: list[dict] = []
    if not valid_date(read.purchased_at, today):
        issues.append(issue(None, None, "invalid_date"))
    if sum(item.price for item in read.items) != read.total:
        issues.append(issue(None, None, "total_mismatch"))
    for index, item in enumerate(read.items):
        if not PRICE_MIN <= item.price <= PRICE_MAX:
            issues.append(issue(index, item.name, "price_out_of_range"))
    return issues
