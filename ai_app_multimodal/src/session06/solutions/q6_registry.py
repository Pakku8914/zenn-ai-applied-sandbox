"""問題6：同じ文書の取り込みを二重に起動しない。進捗は「3/14（21%）」の形で表示する。

    docker compose exec api python -m src.session06.solutions.q6_registry
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from kondate.jobs import FINISHED, JobQueue
from kondate.media import media_path
from src.session06.fakes import RecipeReaderFake
from src.session06.importer import import_recipes, import_total

Work = Callable[[Callable[[int], None]], Awaitable[dict]]


class ImportRegistry:
    """(利用者, 文書) ごとに、終わっていない取り込みジョブを1つだけ持つ。"""

    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue
        self._active: dict[tuple[str, str], str] = {}

    def start(self, user_id: str, document_id: str, work: Work, total: int) -> tuple[str, bool]:
        """(job_id, 新しく作ったか) を返す。中に await が無いので、確かめてから登録するまでに割り込まれない。"""
        key = (user_id, document_id)
        if (job_id := self._active.get(key)) is not None and self._queue.get(job_id).status not in FINISHED:
            return job_id, False
        job = self._queue.submit(work, total)
        self._active[key] = job.id
        return job.id, True


def format_progress(snap: dict) -> str:
    pct = snap["done"] * 100 // snap["total"] if snap["total"] else 0
    return f"{snap['status']} {snap['done']}/{snap['total']}（{pct}%）"


async def settle(queue: JobQueue, job_id: str) -> dict:
    """取り消して、終わった状態のスナップショットを返す。"""
    queue.cancel(job_id)
    async for snap in queue.events(job_id):
        pass
    return snap


def said(created: bool) -> str:
    return "新しく作った" if created else "同じジョブ"


async def demo() -> list[str]:
    raw = media_path("recipe_book_full.pdf").read_bytes()
    queue = JobQueue(concurrency=1)
    registry = ImportRegistry(queue)
    fake = RecipeReaderFake(gate_at=4)  # 4回目の呼び出しで止まったままにする

    def work(progress):
        return import_recipes(fake, raw, 120, progress)

    total = import_total(120)
    first, created = registry.start("u001", "doc_A", work, total)
    lines = [f"1回目: {said(created)}"]
    while fake.calls < 4:
        await asyncio.sleep(0.005)
    second, created = registry.start("u001", "doc_A", work, total)
    lines.append(f"2回目（実行中）: {said(created)}・{format_progress(queue.get(first).snapshot())}・ID が同じ: {second == first}")
    other, created = registry.start("u002", "doc_A", work, total)
    lines.append(f"別の利用者: {said(created)}")
    lines.append(f"取り消したあと: {format_progress(await settle(queue, first))}")
    third, created = registry.start("u001", "doc_A", work, total)
    lines.append(f"もう一度: {said(created)}")
    for job_id in (other, third):  # 片付け（結果は表示しない）
        await settle(queue, job_id)
    return lines


def main() -> None:
    for line in asyncio.run(demo()):
        print(line)


if __name__ == "__main__":
    main()
