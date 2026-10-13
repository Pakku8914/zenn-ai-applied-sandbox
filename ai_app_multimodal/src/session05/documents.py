"""document ブロックの組み立て・トークンの見積もり・テキスト抽出・引用の検証（セッション5）。"""

from __future__ import annotations

import base64
import io
import math
import re
import unicodedata
from dataclasses import dataclass

from pypdf import PdfReader

PDF_TOKENS_PER_PAGE = 1600  # mockllm の近似。本物は1ページごとに「文字のトークン＋ページ画像のトークン」
MIN_QUOTE_CHARS = 6         # これより短い引用は、どのページにも見つかりやすく根拠にならない


# ---------------------------------------------------------------- document ブロックの3つの渡し方

def pdf_block(raw: bytes) -> dict:
    """PDF の中身をリクエストに同封する。API はページの文字と見た目（画像）の両方を読む。"""
    data = base64.standard_b64encode(raw).decode("ascii")
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


def text_block(text: str) -> dict:
    """抜き出した文字だけを文書として渡す。表の罫線・レイアウト・画像は伝わらない。"""
    return {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": text}}


def file_block(file_id: str) -> dict:
    """Files API に預けた PDF を file_id で参照する。"""
    return {"type": "document", "source": {"type": "file", "file_id": file_id}}


# ---------------------------------------------------------------- 入力トークンの見積もり

def estimate_pdf_tokens(pages: int) -> int:
    """PDF をそのまま送るときの見積もり（mockllm の式：ページ数×1600）。"""
    return pages * PDF_TOKENS_PER_PAGE


def estimate_text_tokens(text: str) -> int:
    """文字を送るときの見積もり（mockllm の式：UTF-8 のバイト数÷3 の切り上げ）。"""
    return math.ceil(len(text.encode("utf-8")) / 3)


# ---------------------------------------------------------------- テキスト抽出

def extract_pages(raw: bytes) -> list[str]:
    """pypdf でページごとの文字を抜き出す。文字のデータが無いページ（画像だけ）は空文字になる。"""
    reader = PdfReader(io.BytesIO(raw))
    return [page.extract_text() or "" for page in reader.pages]


# ---------------------------------------------------------------- 引用の検証

def normalize(text: str) -> str:
    """照合用にそろえる。NFKC（全角英数・全角空白・康熙部首を通常の文字へ）→ 空白と改行をすべて除く。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


@dataclass(frozen=True)
class CitationCheck:
    page: int
    quote: str
    ok: bool
    reason: str  # ok / too_short / page_out_of_range / not_found


def check_citation(page_texts: list[str], page: int, quote: str) -> CitationCheck:
    """引用文 quote が、page ページ目（1始まり）の抽出結果に本当にあるかを確かめる。"""
    q = normalize(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return CitationCheck(page, quote, False, "too_short")
    if not 1 <= page <= len(page_texts):
        return CitationCheck(page, quote, False, "page_out_of_range")
    if q not in normalize(page_texts[page - 1]):
        return CitationCheck(page, quote, False, "not_found")
    return CitationCheck(page, quote, True, "ok")
