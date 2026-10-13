"""復習2の入力を作る。どれも検証用メディアから決定的に作る（実写・著作物は使わない）。"""

from __future__ import annotations

import copy
import io
import json
from functools import lru_cache

from pypdf import PdfWriter

from kondate.media import media_path
from src.review02.kit import UPLOAD_MAX_BYTES

TEXT = "鶏むね肉 1枚\n".encode()

# mockllm の receipt シナリオが返す読み取り結果と同じ（receipt.png・receipt.pdf に書かれた内容どおり）
GOOD = {
    "store": "こんだてマート",
    "purchased_at": "2026-10-01",
    "items": [
        {"name": "鶏むね肉", "quantity": 1, "price": 398},
        {"name": "キャベツ", "quantity": 1, "price": 198},
        {"name": "卵（10個入り）", "quantity": 1, "price": 248},
        {"name": "牛乳", "quantity": 1, "price": 228},
    ],
    "total": 1072,
}
BROKEN_JSON = '{"store": "こんだて'  # 途中で途切れた JSON


def receipt_png() -> bytes:
    """600×900 の PNG。"""
    return media_path("receipt.png").read_bytes()


def receipt_pdf() -> bytes:
    """1ページの PDF（文字のデータあり）。"""
    return media_path("receipt.pdf").read_bytes()


@lru_cache
def recipe_book() -> bytes:
    """3ページの PDF（R029 肉じゃが・R011 生姜焼き・R084 みそ汁の順）。"""
    return media_path("recipe_book.pdf").read_bytes()


@lru_cache
def recipe_book_full() -> bytes:
    """120ページの PDF（R001〜R120 が1ページに1件ずつ）。"""
    return media_path("recipe_book_full.pdf").read_bytes()


@lru_cache
def blank_pdf(pages: int) -> bytes:
    """白紙のページだけの PDF。"""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def text_file() -> bytes:
    """ただの文章。名前だけ .pdf にして送られてきた、という想定で使う。"""
    return TEXT


def broken_pdf() -> bytes:
    """先頭だけ PDF の署名で、後ろはただの文章。"""
    return b"%PDF-1.7\n" + TEXT


def oversize_pdf() -> bytes:
    """10MiB を1バイトだけ超えるファイル（先頭は PDF の署名）。"""
    return b"%PDF-" + bytes(UPLOAD_MAX_BYTES + 1 - 5)


def receipt_json(total: int = 1072, prices: dict[int, int] | None = None, **over) -> str:
    """GOOD を元に、一部だけ変えた読み取り結果の JSON。prices は {行の位置: 金額}。"""
    d = copy.deepcopy(GOOD)
    for index, price in (prices or {}).items():
        d["items"][index]["price"] = price
    d.update(total=total, **over)
    return json.dumps(d, ensure_ascii=False)
