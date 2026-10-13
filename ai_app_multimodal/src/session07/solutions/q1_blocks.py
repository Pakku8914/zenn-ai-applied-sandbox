"""問題1：入力の種類で content block を切り替え、入力トークンを送る前に見積もる。

    docker compose exec api python -m src.session07.solutions.q1_blocks
"""

from __future__ import annotations

import io
import math

from anthropic import Anthropic
from PIL import Image
from pypdf import PdfReader

from kondate.media import media_path
from kondate.settings import get_settings
from src.session07.intake import accept_receipt
from src.session07.read import RECEIPT_PROMPT, build_request

# mockllm の近似式（実際の課金とは一致しない）
PATCH, MAX_LONG_EDGE, MAX_IMAGE_TOKENS = 28, 2576, 4784
PDF_TOKENS_PER_PAGE = 1600


def text_tokens(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / 3)


def image_tokens(width: int, height: int) -> int:
    scale = min(1.0, MAX_LONG_EDGE / max(width, height))
    w, h = max(1, round(width * scale)), max(1, round(height * scale))
    return min(MAX_IMAGE_TOKENS, math.ceil(w / PATCH) * math.ceil(h / PATCH))


def estimate(kind: str, data: bytes) -> int:
    """送る直前のバイト列（画像は作り直した JPEG）から、入力トークンを見積もる。"""
    if kind == "image":
        with Image.open(io.BytesIO(data)) as img:
            media = image_tokens(*img.size)
    else:
        media = len(PdfReader(io.BytesIO(data)).pages) * PDF_TOKENS_PER_PAGE
    return 4 + 3 + media + text_tokens(RECEIPT_PROMPT)  # 全体 4 ＋ メッセージ 3 ＋ ブロック


def summary(raw: bytes, client: Anthropic | None = None) -> tuple[str, str, int, int | None]:
    """(ブロックの種類, media_type, 見積もり, count_tokens の値) を返す。client を渡さなければ数えない。"""
    acc = accept_receipt(raw)
    req = build_request(acc.kind, acc.data)
    block = req.messages[0]["content"][0]
    counted = None
    if client is not None:
        counted = client.messages.count_tokens(model=get_settings().llm_model, messages=req.messages).input_tokens
    return block["type"], block["source"]["media_type"], estimate(acc.kind, acc.data), counted


def main() -> None:
    with Anthropic() as client:
        for name in ("receipt.png", "receipt.pdf"):
            print(name, summary(media_path(name).read_bytes(), client))
    # receipt.png ('image', 'image/jpeg', 778, 778)
    # receipt.pdf ('document', 'application/pdf', 1652, 1652)


if __name__ == "__main__":
    main()
