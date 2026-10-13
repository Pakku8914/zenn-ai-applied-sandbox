"""問題4：解凍爆弾の境界と、PDF のページ数の境界を確かめる。

    docker compose exec api python -m src.session02.solutions.p4_bomb
"""

from __future__ import annotations

import asyncio
import io
import warnings
from pathlib import Path

import httpx2
from PIL import Image
from pypdf import PdfWriter

from src.session02.app import MAX_PDF_PAGES, app, upload_dir

OUT = Path("out/s02/solutions")
SIZES = [(8000, 5000), (8000, 6000), (10000, 9000)]


def png(size: tuple[int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("L", size).save(buf, "PNG")  # 1画素1バイトのグレースケール。真っ黒なので圧縮後は小さい
    return buf.getvalue()


def try_open(raw: bytes, strict: bool) -> str:
    """strict=False は Pillow の既定の動き、strict=True は警告を例外に格上げしたときの動き。"""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("error" if strict else "always", Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(raw)):
                pass
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
            return f"{type(e).__name__} で拒否"
    names = sorted({w.category.__name__ for w in caught if issubclass(w.category, Image.DecompressionBombWarning)})
    return f"開ける（{'・'.join(names)}）" if names else "開ける"


def pdf_bytes(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


async def _post_pdf(pages: int) -> str:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/uploads", files={"file": ("book.pdf", pdf_bytes(pages), "application/pdf")})
    body = r.json()
    if r.status_code == 201:
        return f"{pages} ページの PDF → HTTP {r.status_code} kind={body['kind']}"
    return f"{pages} ページの PDF → {r.status_code} {body['error']['type']}「{body['error']['message']}」"


def run() -> list[str]:
    Image.MAX_IMAGE_PIXELS = 40_000_000
    lines = []
    for w, h in SIZES:
        raw = png((w, h))
        lines.append(f"{w}×{h}（{w * h:,} 画素）：既定＝{try_open(raw, False)}／警告を例外に＝{try_open(raw, True)}")
    app.dependency_overrides[upload_dir] = lambda: OUT
    for pages in (MAX_PDF_PAGES, MAX_PDF_PAGES + 1):
        lines.append(asyncio.run(_post_pdf(pages)))
    return lines


if __name__ == "__main__":
    print("\n".join(run()))
