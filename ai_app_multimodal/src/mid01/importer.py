"""レシピ本の取り込み（セッション6の importer.py に、pages.py の分割と documents.py の pdf_block を合わせたもの）。

中間プロジェクト1で変えたのは1か所だけ：import_recipes に used（利用量を入れるリスト）を外から渡せるようにした。
取り消し・失敗でジョブが途中で終わっても、呼び出し側がそこまでに使ったトークンを記録できる。
"""

from __future__ import annotations

import base64
import io
from collections.abc import Callable
from dataclasses import asdict, dataclass

import anyio
from anthropic import transform_schema
from pydantic import BaseModel, Field, ValidationError
from pypdf import PdfReader, PdfWriter

from kondate.llm import ChatRequest, LLMProvider, Usage

CHUNK_PAGES = 10          # 1回に読ませるページ数
CHUNK_OVERLAP = 1         # 隣の範囲と重ねるページ数
IMPORT_MAX_TOKENS = 2048
MAX_ATTEMPTS = 2
IMPORT_SYSTEM = "添付のPDFはレシピ本の一部です。載っているレシピをすべて書き出してください。pageは添付PDFの中でのページ番号（1始まり）です。"
IMPORT_PROMPT = "このPDFのレシピをすべて書き出してください。"


# ---------------------------------------------------------------- document ブロックと分割（documents.py・pages.py）

def pdf_block(raw: bytes) -> dict:
    data = base64.standard_b64encode(raw).decode("ascii")
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


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
    parts = []
    for start, end in ranges:
        writer = PdfWriter()
        for p in range(start, end + 1):
            writer.add_page(reader.pages[p - 1])
        buf = io.BytesIO()
        writer.write(buf)
        parts.append(buf.getvalue())
    return parts


# ---------------------------------------------------------------- 読ませて統合する（importer.py）

class ChunkRecipe(BaseModel):
    id: str = Field(pattern=r"^R\d{3}$", description="レシピ ID（R029 の形）")
    name: str = Field(min_length=1)
    page: int = Field(ge=1, description="添付 PDF の中でのページ番号（1始まり）")
    minutes: int = Field(ge=1)
    servings: int = Field(ge=1)
    kcal: int = Field(ge=0)


class ChunkRecipes(BaseModel):
    recipes: list[ChunkRecipe]


CHUNK_SCHEMA = transform_schema(ChunkRecipes)


@dataclass(frozen=True)
class ImportedRecipe:
    id: str
    name: str
    page: int  # 元の PDF でのページ番号
    minutes: int
    servings: int
    kcal: int


def import_total(pages: int) -> int:
    return len(chunk_ranges(pages, CHUNK_PAGES, CHUNK_OVERLAP))


async def read_chunk(llm: LLMProvider, part: bytes, start: int, end: int, used: list[Usage]) -> list[ImportedRecipe] | None:
    req = ChatRequest(
        messages=[{"role": "user", "content": [pdf_block(part), {"type": "text", "text": IMPORT_PROMPT}]}],
        system=IMPORT_SYSTEM,
        output_schema=CHUNK_SCHEMA,
        max_tokens=IMPORT_MAX_TOKENS,
    )
    for _ in range(MAX_ATTEMPTS):
        result = await llm.complete(req)
        used.append(result.usage)
        if result.stop_reason == "max_tokens":
            return None
        try:
            parsed = ChunkRecipes.model_validate_json(result.text)
        except ValidationError:
            continue
        if any(r.page > end - start + 1 for r in parsed.recipes):
            continue
        return [ImportedRecipe(r.id, r.name, start + r.page - 1, r.minutes, r.servings, r.kcal) for r in parsed.recipes]
    return None


def merge(records: list[ImportedRecipe], pages: int) -> dict:
    by_id: dict[str, ImportedRecipe] = {}
    duplicates, conflicts = 0, set()
    for r in records:
        first = by_id.setdefault(r.id, r)
        if first is r:
            continue
        if first == r:
            duplicates += 1
        else:
            conflicts.add(r.id)
    recipes = sorted(by_id.values(), key=lambda r: (r.page, r.id))
    covered = {r.page for r in recipes}
    return {
        "recipes": recipes,
        "duplicates_removed": duplicates,
        "conflicts": sorted(conflicts),
        "missing_pages": [p for p in range(1, pages + 1) if p not in covered],
    }


async def import_recipes(
    llm: LLMProvider, raw: bytes, pages: int, progress: Callable[[int], None], used: list[Usage] | None = None,
) -> dict:
    """PDF 全体を分割して読み、統合した結果を返す。used を渡すと、試行ごとの利用量をそこへ足していく。"""
    used = [] if used is None else used
    ranges = chunk_ranges(pages, CHUNK_PAGES, CHUNK_OVERLAP)
    parts = await anyio.to_thread.run_sync(split_pdf, raw, ranges)
    records: list[ImportedRecipe] = []
    unreadable: list[int] = []
    for i, ((start, end), part) in enumerate(zip(ranges, parts, strict=True), 1):
        got = await read_chunk(llm, part, start, end, used)
        if got is None:
            unreadable.append(i)
        else:
            records.extend(got)
        progress(i)
    merged = merge(records, pages)
    return {
        "pages": pages,
        "chunks": len(ranges),
        "imported": len(merged["recipes"]),
        "duplicates_removed": merged["duplicates_removed"],
        "conflicts": merged["conflicts"],
        "missing_pages": merged["missing_pages"],
        "unreadable_chunks": unreadable,
        "needs_review": bool(merged["conflicts"] or merged["missing_pages"] or unreadable),
        "recipes": [asdict(r) for r in merged["recipes"]],
        "usage": {
            "input_tokens": sum(u.input_tokens for u in used),
            "output_tokens": sum(u.output_tokens for u in used),
        },
    }
