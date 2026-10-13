"""問題6：大きな PDF・偽装した PDF を uploads と documents → import-recipes に流し、どこで止まるかを確かめる。

    docker compose exec api python -m src.review02.solutions.q6_where
"""

from __future__ import annotations

import asyncio

import anyio

from src.review02 import samples
from src.review02.kit import (
    MSG_TOO_LARGE, UPLOAD_MAX_BYTES, RecipeReaderFake, Rejected, import_recipes, inspect_pdf, inspect_upload,
)


def via_uploads(raw: bytes) -> str:
    """セッション2の /api/uploads。"""
    if len(raw) > UPLOAD_MAX_BYTES:
        return "413 too_large"
    try:
        kind, _ = inspect_upload(raw)
    except Rejected as e:
        return f"{e.status} {e.type}"
    return f"201 {kind}"


async def via_documents(raw: bytes) -> tuple[str, str, int]:
    """セッション5・6の /api/documents → import-recipes。(登録の結果, 取り込みの結果, LLM の呼び出し回数)。"""
    if len(raw) > UPLOAD_MAX_BYTES:
        return f"413 too_large「{MSG_TOO_LARGE}」", "なし", 0
    try:
        pages, _ = await anyio.to_thread.run_sync(inspect_pdf, raw)
    except Rejected as e:
        return f"{e.status} {e.type}「{e.message}」", "なし", 0  # 登録できなければ document_id が無く、取り込みも頼めない
    fake = RecipeReaderFake()
    progress: list[int] = []
    r = await import_recipes(fake, raw, pages, progress.append)
    assert progress == list(range(1, r["chunks"] + 1))  # 範囲を1つ読み終えるたびに1つ進む
    summary = (f"{r['chunks']} 回に分けて {r['imported']} 件・重複除去 {r['duplicates_removed']}・"
               f"取りこぼし {len(r['missing_pages'])} ページ・入力 {r['usage']['input_tokens']}")
    return f"201 {pages}ページ", summary, fake.calls


async def run() -> None:
    cases = [
        ("recipe_book_full.pdf（120ページ）", samples.recipe_book_full()),
        ("白紙の PDF（200ページ）", samples.blank_pdf(200)),
        ("白紙の PDF（201ページ）", samples.blank_pdf(201)),
        ("中身は文章（名前は book.pdf）", samples.text_file()),
        ("先頭だけ %PDF- の壊れたファイル", samples.broken_pdf()),
        ("receipt.png", samples.receipt_png()),
        ("10MiB を1バイト超える PDF", samples.oversize_pdf()),
    ]
    for label, raw in cases:
        document, imported, calls = await via_documents(raw)
        print(f"{label} → uploads {via_uploads(raw)} ／ documents {document} ／ import {imported}・LLM {calls} 回")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
