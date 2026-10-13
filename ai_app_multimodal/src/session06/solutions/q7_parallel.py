"""問題7（発展）：範囲を同時に最大3つまで読み、終わる順番が変わっても結果が逐次版と同じになるようにする。

    docker compose exec api python -m src.session06.solutions.q7_parallel
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace

import anyio

from kondate.llm import ChatRequest, ChatResult, LLMProvider, Usage
from kondate.media import media_path
from src.session06.fakes import RecipeReaderFake
from src.session06.importer import CHUNK_OVERLAP, CHUNK_PAGES, ImportedRecipe, import_recipes, merge, read_chunk
from src.session06.pages import chunk_ranges, split_pdf


async def import_parallel(llm: LLMProvider, raw: bytes, pages: int, progress: Callable[[int], None],
                          concurrency: int = 3) -> dict:
    ranges = chunk_ranges(pages, CHUNK_PAGES, CHUNK_OVERLAP)
    parts = await anyio.to_thread.run_sync(split_pdf, raw, ranges)
    sem = asyncio.Semaphore(concurrency)
    used: list[Usage] = []
    done = 0

    async def one(i: int) -> list[ImportedRecipe] | None:
        nonlocal done
        async with sem:
            got = await read_chunk(llm, parts[i], *ranges[i], used)
        done += 1
        progress(done)  # 終わった数で通知する（何番目の範囲が終わったかではない）
        return got

    results = await asyncio.gather(*(one(i) for i in range(len(ranges))))  # 結果は範囲の順に並ぶ
    records = [r for got in results if got for r in got]                   # 範囲の順に統合する
    merged = merge(records, pages)
    return {
        "imported": len(merged["recipes"]),
        "duplicates_removed": merged["duplicates_removed"],
        "conflicts": merged["conflicts"],
        "missing_pages": merged["missing_pages"],
        "unreadable_chunks": [i + 1 for i, got in enumerate(results) if got is None],
        "recipes": merged["recipes"],
        "input_tokens": sum(u.input_tokens for u in used),
    }


class SlowFake:
    """呼び出しごとに違う長さだけ待ってから RecipeReaderFake に読ませる（終わる順番をばらばらにする）。

    さらに「範囲の先頭ページにある R010」だけ調理時間を10分多く読み違える。
    R010 は 1〜10 の範囲では末尾、10〜19 の範囲では先頭にあるので、2個目の範囲だけが間違える。
    """

    name = "slow-fake"

    def __init__(self) -> None:
        self.inner = RecipeReaderFake()
        self.calls = self.running = self.peak = 0

    async def complete(self, req: ChatRequest) -> ChatResult:
        self.calls += 1
        n = self.calls
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await asyncio.sleep(0.002 * (1 + (n * 7) % 5))
            result = await self.inner.complete(req)
        finally:
            self.running -= 1
        data = json.loads(result.text)
        for r in data["recipes"]:
            if r["id"] == "R010" and r["page"] == 1:
                r["minutes"] += 10
        return replace(result, text=json.dumps(data, ensure_ascii=False))

    async def stream(self, req: ChatRequest):
        raise NotImplementedError
        yield


async def demo() -> list[str]:
    raw = media_path("recipe_book_full.pdf").read_bytes()
    seen: list[int] = []
    slow = SlowFake()
    par = await import_parallel(slow, raw, 120, seen.append)
    seq = await import_recipes(SlowFake(), raw, 120, lambda _: None)
    same = ([(r.id, r.page, r.minutes) for r in par["recipes"]] == [(r["id"], r["page"], r["minutes"]) for r in seq["recipes"]]
            and (par["conflicts"], par["duplicates_removed"]) == (seq["conflicts"], seq["duplicates_removed"]))
    return [
        f"同時に読んだ範囲の最大数: {slow.peak}",
        f"逐次版と同じ結果: {same}（{par['imported']}件・食い違い {par['conflicts']}）",
        f"進捗の通知: {len(seen)} 回・最後は {seen[-1]}/{len(seen)}・単調に増える: {seen == sorted(seen)}",
        f"入力トークン: {par['input_tokens']:,}",
    ]


def main() -> None:
    for line in asyncio.run(demo()):
        print(line)


if __name__ == "__main__":
    main()
