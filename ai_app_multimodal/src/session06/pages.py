"""大きな文書の下ごしらえ（セッション6）：上限・見出しの索引・ページ選択・分割の範囲。"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter

from src.session06.documents import normalize

# ---------------------------------------------------------------- 上限
API_MAX_PAGES = 600                 # API の PDF の上限（2026-10-02 時点。改訂で変わりやすい）
API_MAX_REQUEST_BYTES = 32_000_000  # 「32MB」。2進か10進か迷う値は、小さい方で判定しておく
APP_MAX_PAGES = 200                 # 受付の上限（セッション2で決めた値）
ASK_MAX_PAGES = 20                  # 1回の質問で送るページの上限（本章で決めた値）


def base64_size(n: int) -> int:
    """n バイトを base64 にしたときの長さ。3バイトごとに4文字になるので、約 4/3 倍に膨らむ。"""
    return 4 * math.ceil(n / 3)


# ---------------------------------------------------------------- 見出しの索引（目次の代わり）
# 各ページの2行目は「R029　調理時間 35分　4人分　1人分 250kcal」。normalize で空白を消してから読む
HEADING = re.compile(r"(R\d{3})調理時間(\d+)分(\d+)人分1人分(\d+)kcal")


@dataclass(frozen=True)
class Heading:
    page: int  # 元の PDF でのページ番号（1始まり）
    recipe_id: str
    name: str
    minutes: int
    servings: int
    kcal: int


def parse_heading(text: str, page: int) -> Heading | None:
    """1ページ分の抽出結果から、料理名（1行目）と ID の行（2行目）を読む。読めなければ None。"""
    t = normalize(text)  # NFKC＋空白の除去。康熙部首の「⾁」も「肉」になる
    m = HEADING.search(t)
    if m is None:
        return None
    return Heading(page, m[1], t[: m.start()], int(m[2]), int(m[3]), int(m[4]))


def build_index(page_texts: list[str]) -> list[Heading]:
    """全ページの見出しを集める。見出しの読めないページ（表紙・画像だけのページ）は載らない。"""
    return [h for i, text in enumerate(page_texts, 1) if (h := parse_heading(text, i)) is not None]


def guess_pages(index: list[Heading], question: str) -> list[int]:
    """質問に料理名がそのまま含まれるページを返す。当たりを付けるだけなので、外れたら pages で指定してもらう。"""
    q = normalize(question)
    return sorted({h.page for h in index if h.name and h.name in q})


# ---------------------------------------------------------------- ページ選択と分割

def _write(reader: PdfReader, pages: list[int]) -> bytes:
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def select_pages(raw: bytes, pages: list[int]) -> bytes:
    """pages（1始まり）のページだけを、この順に並べた新しい PDF を作る。"""
    return _write(PdfReader(io.BytesIO(raw)), pages)


def chunk_ranges(pages: int, size: int, overlap: int) -> list[tuple[int, int]]:
    """1〜pages を size ページずつに分ける。隣り合う範囲は overlap ページ重ねる（境界をまたぐ内容を取りこぼさない）。"""
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
    """範囲ごとに PDF を作る（元の PDF は1回だけ開く）。"""
    reader = PdfReader(io.BytesIO(raw))
    return [_write(reader, list(range(start, end + 1))) for start, end in ranges]
