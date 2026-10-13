"""問題3：読むページを選んで新しい PDF を作り、引用のページ番号を元の番号に戻す。

    docker compose exec api python -m src.session06.solutions.q3_select
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from anthropic import Anthropic
from pypdf import PdfReader, PdfWriter

from kondate.media import media_path
from kondate.settings import get_settings
from src.session06.documents import extract_pages, pdf_block
from src.session06.pages import parse_heading


@dataclass(frozen=True)
class Selection:
    data: bytes = field(repr=False)
    sent: list[int]  # 送った PDF の i ページ目（1始まり）が、元の sent[i-1] ページ


def select(raw: bytes, pages: list[int]) -> Selection:
    reader = PdfReader(io.BytesIO(raw))
    sent = sorted(set(pages))
    if not sent or sent[0] < 1 or sent[-1] > len(reader.pages):
        raise ValueError(f"pages は 1〜{len(reader.pages)} の範囲で1つ以上指定してください")
    writer = PdfWriter()
    for p in sent:
        writer.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return Selection(buf.getvalue(), sent)


def to_original(sel: Selection, page: int) -> int:
    if not 1 <= page <= len(sel.sent):
        raise ValueError(f"送った PDF は {len(sel.sent)} ページです（{page} は範囲外）")
    return sel.sent[page - 1]


def main() -> None:
    full = media_path("recipe_book_full.pdf").read_bytes()
    sel = select(full, [84, 29, 29, 11])
    client = Anthropic()
    try:
        n = client.messages.count_tokens(model=get_settings().llm_model,
                                         messages=[{"role": "user", "content": [pdf_block(sel.data)]}]).input_tokens
    finally:
        client.close()
    ids = [parse_heading(t, i).recipe_id for i, t in enumerate(extract_pages(sel.data), 1)]
    print(f"送るページ: {sel.sent}")
    print(f"count_tokens: {n}")
    print(f"送った PDF の見出し: {ids}")
    print(f"送った PDF の 2 ページ目 → 元の {to_original(sel, 2)} ページ")
    for bad in ([], [0], [121]):
        try:
            select(full, bad)
        except ValueError:
            print(f"{bad} → ValueError")


if __name__ == "__main__":
    main()
