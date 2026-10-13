"""大きな文書の下ごしらえ（セッション6の pages.py の写し）：見出しの索引・ページ選択・分割の範囲。"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter

from src.final.documents import normalize

ASK_MAX_PAGES = 20
HEADING = re.compile(r"(R\d{3})調理時間(\d+)分(\d+)人分1人分(\d+)kcal")


@dataclass(frozen=True)
class Heading:
    page: int
    recipe_id: str
    name: str
    minutes: int
    servings: int
    kcal: int


def parse_heading(text: str, page: int) -> Heading | None:
    t = normalize(text)
    m = HEADING.search(t)
    if m is None:
        return None
    return Heading(page, m[1], t[: m.start()], int(m[2]), int(m[3]), int(m[4]))


def build_index(page_texts: list[str]) -> list[Heading]:
    return [h for i, text in enumerate(page_texts, 1) if (h := parse_heading(text, i)) is not None]


def guess_pages(index: list[Heading], question: str) -> list[int]:
    q = normalize(question)
    return sorted({h.page for h in index if h.name and h.name in q})


def _write(reader: PdfReader, pages: list[int]) -> bytes:
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def select_pages(raw: bytes, pages: list[int]) -> bytes:
    return _write(PdfReader(io.BytesIO(raw)), pages)


def chunk_ranges(pages: int, size: int, overlap: int) -> list[tuple[int, int]]:
    if pages < 1 or not 0 <= overlap < size:
        raise ValueError("pages は 1 以上、overlap は 0 以上 size 未満にしてください")
    ranges: list[tuple[int, int]] = []
    start = 1
    while True:
        end = min(start + size - 1, pages)
        ranges.append((start, end))
        if end == pages:
            return ranges
        start = end - overlap + 1


def split_pdf(raw: bytes, ranges: list[tuple[int, int]]) -> list[bytes]:
    reader = PdfReader(io.BytesIO(raw))
    return [_write(reader, list(range(start, end + 1))) for start, end in ranges]
