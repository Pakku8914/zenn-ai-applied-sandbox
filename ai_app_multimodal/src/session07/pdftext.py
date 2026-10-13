"""PDF の文字（pypdf）を先に読み、LLM の読み取り結果と突き合わせる（セッション7）。

比べるもの（本書で決めた規則）：
- 購入日：PDF の最初の「YYYY-MM-DD」と、読み取った purchased_at（時刻は比べない）
- 合計：PDF の「合計 ¥1,072」の額と、読み取った total
- 各行：品名が PDF の文字に含まれ、金額が PDF の「¥〜」の額のどれかと同じか
店名は比べない（「こんだてマート 本店」のような表記ゆれが多く、家計の数字に影響しないため）。
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass

from pypdf import PdfReader

from src.session07.checks import issue
from src.session07.models import ReceiptRead

AMOUNT = r"(\d{1,3}(?:,\d{3})+|\d+)"          # 1,072 のような桁区切りも、398 のような素の数字も
YEN = re.compile(r"¥\s*" + AMOUNT)
TOTAL = re.compile(r"合計\s*¥\s*" + AMOUNT)
DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def nfkc(text: str) -> str:
    """全角の数字・記号（￥・１）と、康熙部首の「⾁」などを通常の文字にそろえる（セッション5と同じ考え方）。"""
    return unicodedata.normalize("NFKC", text)


def squash(text: str) -> str:
    """NFKC にそろえ、空白と改行をすべて除く。品名の照合に使う。"""
    return re.sub(r"\s+", "", nfkc(text))


def yen(value: str) -> int:
    return int(value.replace(",", ""))


@dataclass(frozen=True)
class ReceiptText:
    squashed: str              # 空白を除いた全文（品名の照合用）
    purchased_at: str | None   # PDF に書かれた購入日（YYYY-MM-DD）。見つからなければ None
    total: int | None          # PDF に書かれた合計。見つからなければ None
    amounts: frozenset[int]    # PDF に書かれた「¥〜」の額すべて


def extract_text(raw: bytes) -> str:
    """pypdf で全ページの文字を抜き出す。文字のデータが無い PDF（スキャン）や抜き出せない PDF は空文字。"""
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    except Exception:  # 壊れ方によって pypdf の例外はさまざま。突き合わせができないだけなので空文字にする
        return ""


def parse_receipt_text(text: str) -> ReceiptText | None:
    """抜き出した文字から、突き合わせに使う値を拾う。文字が1つも無ければ None（突き合わせをしない）。"""
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
    """PDF の文字と食い違う所に text_mismatch の印を付ける。日付・合計はまとめて1件、各行は1行1件。"""
    issues: list[dict] = []
    date_differs = text.purchased_at is not None and text.purchased_at != read.purchased_at
    total_differs = text.total is not None and text.total != read.total
    if date_differs or total_differs:
        issues.append(issue(None, None, "text_mismatch"))
    for index, item in enumerate(read.items):
        if squash(item.name) not in text.squashed or item.price not in text.amounts:
            issues.append(issue(index, item.name, "text_mismatch"))
    return issues
