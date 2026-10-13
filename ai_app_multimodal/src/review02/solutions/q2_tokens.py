"""問題2：画像・PDF・ページ選択した PDF の入力トークンを式で組み立て、count_tokens と突き合わせる。

    docker compose exec api python -m src.review02.solutions.q2_tokens
"""

from __future__ import annotations

import base64
import io
import math

from anthropic import Anthropic
from PIL import Image
from pypdf import PdfReader

from kondate.settings import get_settings
from src.review02 import samples
from src.review02.kit import (
    PDF_TOKENS_PER_PAGE, RECEIPT_PROMPT, SYSTEM_PROMPT,
    accept_receipt, estimate_image_tokens, pdf_block, receipt_block, select_pages,
)

QUESTION = "肉じゃがは何人分ですか？"


def text_tokens(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / 3)


def media_tokens(block: dict) -> int:
    """送るブロックの中身から数える。画像は寸法（セッション3）、PDF はページ数（セッション5）。"""
    raw = base64.b64decode(block["source"]["data"])
    if block["type"] == "image":
        with Image.open(io.BytesIO(raw)) as img:
            return estimate_image_tokens(*img.size)
    return len(PdfReader(io.BytesIO(raw)).pages) * PDF_TOKENS_PER_PAGE


def breakdown(block: dict, text: str, system: str | None) -> tuple[int, int, int, int, int]:
    """(枠, system, 画像か文書, テキスト, 合計)。"""
    frame = 4 + 3  # リクエスト1件の 4 ＋ メッセージ1件の 3
    s = text_tokens(system) if system else 0
    m = media_tokens(block)
    t = text_tokens(text)
    return frame, s, m, t, frame + s + m + t


def counted(client: Anthropic, block: dict, text: str, system: str | None) -> int:
    kw = {"system": system} if system else {}
    messages = [{"role": "user", "content": [block, {"type": "text", "text": text}]}]
    return client.messages.count_tokens(model=get_settings().llm_model, messages=messages, **kw).input_tokens


def cases() -> list[tuple[str, dict, str, str | None]]:
    png = accept_receipt(samples.receipt_png())  # セッション7の受付：EXIF なしの JPEG に作り直す
    full = samples.recipe_book_full()
    return [
        ("receipt.png（前処理あり）＋取り込みの指示", receipt_block(png.kind, png.data), RECEIPT_PROMPT, None),
        ("receipt.pdf＋取り込みの指示", receipt_block("pdf", samples.receipt_pdf()), RECEIPT_PROMPT, None),
        ("recipe_book.pdf（3ページ）＋質問", pdf_block(samples.recipe_book()), QUESTION, SYSTEM_PROMPT),
        ("recipe_book_full.pdf の [29]＋質問", pdf_block(select_pages(full, [29])), QUESTION, SYSTEM_PROMPT),
        ("recipe_book_full.pdf の [11, 29, 84]＋質問", pdf_block(select_pages(full, [11, 29, 84])), QUESTION, SYSTEM_PROMPT),
        ("recipe_book_full.pdf（120ページ）全体＋質問", pdf_block(full), QUESTION, SYSTEM_PROMPT),
    ]


def main() -> None:
    with Anthropic() as client:
        for label, block, text, system in cases():
            f, s, m, t, total = breakdown(block, text, system)
            c = counted(client, block, text, system)
            kind = "画像" if block["type"] == "image" else "文書"
            print(f"{label}: 枠 {f} + system {s} + {kind} {m} + テキスト {t} = {total} ／ count_tokens {c} ／ {'一致' if c == total else '不一致'}")


if __name__ == "__main__":
    main()
