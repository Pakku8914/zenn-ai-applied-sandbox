"""document ブロックの組み立て・テキスト抽出・引用の検証（セッション6の documents.py の写し。使う関数だけ）。"""

from __future__ import annotations

import base64
import io
import re
import unicodedata
from dataclasses import dataclass

from pypdf import PdfReader

MIN_QUOTE_CHARS = 6


def pdf_block(raw: bytes) -> dict:
    data = base64.standard_b64encode(raw).decode("ascii")
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


def cached(block: dict) -> dict:
    """このブロックまで（system も含む）を、プロンプトキャッシュの接頭辞にする印を付ける。"""
    return {**block, "cache_control": {"type": "ephemeral"}}


def extract_pages(raw: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(raw))
    return [page.extract_text() or "" for page in reader.pages]


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


@dataclass(frozen=True)
class CitationCheck:
    page: int
    quote: str
    ok: bool
    reason: str  # ok / too_short / page_out_of_range / not_found


def check_citation(page_texts: list[str], page: int, quote: str) -> CitationCheck:
    q = normalize(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return CitationCheck(page, quote, False, "too_short")
    if not 1 <= page <= len(page_texts):
        return CitationCheck(page, quote, False, "page_out_of_range")
    if q not in normalize(page_texts[page - 1]):
        return CitationCheck(page, quote, False, "not_found")
    return CitationCheck(page, quote, True, "ok")
