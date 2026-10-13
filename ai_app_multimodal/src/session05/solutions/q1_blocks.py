"""問題1：document ブロックを3通りで組み立て、入力トークンを見積もって count_tokens と照合する。

    docker compose exec api python -m src.session05.solutions.q1_blocks
"""

from __future__ import annotations

import base64
import io
import math

from anthropic import Anthropic
from pypdf import PdfReader

from kondate.media import media_path
from kondate.settings import get_settings

FRAME_TOKENS = 4 + 3             # リクエスト1件（4）とメッセージ1件（3）の枠
PDF_TOKENS_PER_PAGE = 1600       # mockllm の式：PDF はページ数×1600
UNKNOWN_DOCUMENT_TOKENS = 1600   # file 参照は中身が見えないので、mockllm は固定で数える
SAMPLE_TEXT = "肉じゃが（R029）は4人分、調理時間は35分です。"
SAMPLE_FILE_ID = "file_demo_recipe_book_0001"


def make_document_block(kind: str, value: bytes | str) -> dict:
    if kind == "base64":
        if not isinstance(value, bytes) or not value.startswith(b"%PDF-"):
            raise ValueError("base64 には PDF のバイト列を渡してください")
        data = base64.standard_b64encode(value).decode("ascii")
        source = {"type": "base64", "media_type": "application/pdf", "data": data}
    elif kind == "text":
        if not isinstance(value, str) or not value:
            raise ValueError("text には空でない文字列を渡してください")
        source = {"type": "text", "media_type": "text/plain", "data": value}
    elif kind == "file":
        if not isinstance(value, str) or not value.startswith("file_"):
            raise ValueError("file_id は file_ で始まる文字列にしてください")
        source = {"type": "file", "file_id": value}
    else:
        raise ValueError(f"kind は base64・text・file のいずれかです（{kind!r}）")
    return {"type": "document", "source": source}


def estimate(block: dict) -> int:
    """ブロック1つを user メッセージ1件で送ったときの input_tokens を見積もる（枠の 7 を含む）。"""
    src = block["source"]
    if src["type"] == "base64":
        pages = len(PdfReader(io.BytesIO(base64.b64decode(src["data"]))).pages)
        body = pages * PDF_TOKENS_PER_PAGE
    elif src["type"] == "text":
        body = math.ceil(len(src["data"].encode("utf-8")) / 3)
    else:
        body = UNKNOWN_DOCUMENT_TOKENS
    return FRAME_TOKENS + body


def count(client: Anthropic, block: dict) -> int:
    res = client.messages.count_tokens(model=get_settings().llm_model, messages=[{"role": "user", "content": [block]}])
    return res.input_tokens


def blocks() -> dict[str, dict]:
    return {
        "base64": make_document_block("base64", media_path("recipe_book.pdf").read_bytes()),
        "text": make_document_block("text", SAMPLE_TEXT),
        "file": make_document_block("file", SAMPLE_FILE_ID),
    }


def main() -> None:
    client = Anthropic()
    try:
        for name, block in blocks().items():
            print(f"{name}: 見積もり {estimate(block)} ／ count_tokens {count(client, block)}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
