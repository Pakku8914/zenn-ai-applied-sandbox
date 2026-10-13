"""PDF の受付・document ブロック・引用の検証（セッション5・6の documents.py と app.py から必要な分をコピー）。"""

from __future__ import annotations

import base64
import io
import re
import unicodedata

from pypdf import PdfReader

from src.session14.intake import Rejected

MAX_PDF_PAGES = 200          # 受付の上限（セッション2）
MIN_QUOTE_CHARS = 6
MSG_NOT_PDF = "PDF を送ってください"
MSG_TOO_MANY_PAGES = f"PDF は {MAX_PDF_PAGES} ページ以下にしてください"


def pdf_block(raw: bytes) -> dict:
    data = base64.standard_b64encode(raw).decode("ascii")
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


def cached(block: dict) -> dict:
    """このブロックまで（system も含む）を、プロンプトキャッシュの接頭辞にする印を付ける（セッション6）。"""
    return {**block, "cache_control": {"type": "ephemeral"}}


def extract_pages(raw: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(raw))
    return [page.extract_text() or "" for page in reader.pages]


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
    except Exception:
        texts = [""] * pages
    return pages, texts


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def quote_exists(page_texts: list[str], page: int, quote: str) -> bool:
    """引用文 quote が page ページ目（1始まり）の抽出結果に本当にあるか（自前の引用の検証）。"""
    q = normalize(quote)
    return len(q) >= MIN_QUOTE_CHARS and 1 <= page <= len(page_texts) and q in normalize(page_texts[page - 1])
