"""PDF の文字（pypdf）と読み取り結果の突き合わせ（セッション7の pdftext.py と同じ。import 先だけ変えた）。"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass

from pypdf import PdfReader

from src.mid01.receipt import ReceiptRead, issue

AMOUNT = r"(\d{1,3}(?:,\d{3})+|\d+)"
YEN = re.compile(r"¥\s*" + AMOUNT)
TOTAL = re.compile(r"合計\s*¥\s*" + AMOUNT)
DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def squash(text: str) -> str:
    return re.sub(r"\s+", "", nfkc(text))


def yen(value: str) -> int:
    return int(value.replace(",", ""))


@dataclass(frozen=True)
class ReceiptText:
    squashed: str
    purchased_at: str | None
    total: int | None
    amounts: frozenset[int]


def extract_text(raw: bytes) -> str:
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    except Exception:
        return ""


def parse_receipt_text(text: str) -> ReceiptText | None:
    t = nfkc(text)
    if not squash(t):
        return None
    day = DATE.search(t)
    total = TOTAL.search(t)
    return ReceiptText(
        squashed=squash(t),
        purchased_at=day.group(0) if day else None,
        total=yen(total.group(1)) if total else None,
        amounts=frozenset(yen(a) for a in YEN.findall(t)),
    )


def compare_with_text(read: ReceiptRead, text: ReceiptText) -> list[dict]:
    issues: list[dict] = []
    date_differs = text.purchased_at is not None and text.purchased_at != read.purchased_at
    total_differs = text.total is not None and text.total != read.total
    if date_differs or total_differs:
        issues.append(issue(None, None, "text_mismatch"))
    for index, item in enumerate(read.items):
        if squash(item.name) not in text.squashed or item.price not in text.amounts:
            issues.append(issue(index, item.name, "text_mismatch"))
    return issues
