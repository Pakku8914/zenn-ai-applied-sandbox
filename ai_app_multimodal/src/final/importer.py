"""レシピ本の取り込み（セッション6の importer.py の写し）。

最終プロジェクトで変えたのは1か所だけ：使ったトークンを、呼び出し側から渡された used に足していく
（ジョブが失敗・取り消しで終わっても、それまでに使った分を利用量に記録できるように）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass

import anyio
from anthropic import transform_schema
from pydantic import BaseModel, Field, ValidationError

from kondate.llm import ChatRequest, LLMProvider, Usage
from src.final.documents import pdf_block
from src.final.pages import chunk_ranges, split_pdf

CHUNK_PAGES = 10
CHUNK_OVERLAP = 1
IMPORT_MAX_TOKENS = 2048
MAX_ATTEMPTS = 2
IMPORT_SYSTEM = "添付のPDFはレシピ本の一部です。載っているレシピをすべて書き出してください。pageは添付PDFの中でのページ番号（1始まり）です。"
IMPORT_PROMPT = "このPDFのレシピをすべて書き出してください。"


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
    page: int
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
        result = await llm.complete(req)  # 上流の失敗はそのまま上げ、ジョブの失敗にする
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


async def import_recipes(llm: LLMProvider, raw: bytes, pages: int, progress: Callable[[int], None],
                         used: list[Usage]) -> dict:
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
