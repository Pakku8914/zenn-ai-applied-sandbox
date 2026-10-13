"""問題7：失敗したあとに何が残るか。レシートの再送（セッション4・7）と、取り込みジョブの取り消し・上流の失敗（セッション6）。

    docker compose exec api python -m src.review02.solutions.q7_after_failure
"""

from __future__ import annotations

import asyncio
import logging

import httpx2
from anthropic import AsyncAnthropic

from kondate.clock import FixedClock
from kondate.jobs import Job, JobQueue
from kondate.llm import AnthropicProvider, ChatResult, FakeProvider, LLMProvider, Usage
from kondate.settings import get_settings
from src.review02 import samples
from src.review02.kit import DOC_MSG_UPSTREAM, Counting, Outcome, RecipeReaderFake, import_recipes, import_total
from src.review02.solutions.q1_windows import Receipts

logging.getLogger("src.review02").setLevel(logging.ERROR)  # 壊れた JSON の警告ログを出さない
MOCK = get_settings().mockllm_url


def start(queue: JobQueue, llm: LLMProvider, raw: bytes, pages: int) -> Job:
    async def work(progress) -> dict:
        return await import_recipes(llm, raw, pages, progress)
    return queue.submit(work, total=import_total(pages))


async def follow(queue: JobQueue, job: Job) -> str:
    """SSE（セッション6）と同じ順：progress を最後まで受け、終わり方に応じて done か error を足す。"""
    last: dict = {}
    async for snap in queue.events(job.id):
        last = snap
    head = f"{last['status']} {last['done']}/{last['total']}"
    if job.status == "succeeded":
        return f"{head} → done・{job.result['imported']} 件"
    if job.status == "failed":
        return f"{head} → error「{DOC_MSG_UPSTREAM}」"
    return f"{head} → progress だけで終わる"  # cancelled：途中までの結果は捨てる


def show(o: Outcome, calls: int) -> str:
    head = (f"{o.status} {o.body['source']}" if o.status == 201
            else f"{o.status} {o.body['error']['type']}「{o.body['error']['message']}」")
    return f"{head}・usage {o.usage.input_tokens}/{o.usage.output_tokens}・LLM {calls} 回"


async def receipts_part(mock: LLMProvider, faulty: LLMProvider) -> None:
    receipts = Receipts(FixedClock().now().date())
    broken = [ChatResult(samples.BROKEN_JSON, [], "end_turn", Usage(778, 104))] * 2
    png, pdf = samples.receipt_png(), samples.receipt_pdf()
    cases = [
        ("receipt.png・壊れた JSON が2回", png, FakeProvider(broken)),
        ("receipt.png・再送（mockllm）", png, mock),
        ("receipt.png・もう一度", png, mock),
        ("receipt.pdf・上流が 529", pdf, faulty),
        ("receipt.pdf・再送（mockllm）", pdf, mock),
    ]
    for label, raw, llm in cases:
        counting = Counting(llm)
        o = await receipts.import_("u001", raw, counting)
        print(f"{label} → {show(o, counting.calls)}")


async def jobs_part(faulty: LLMProvider) -> None:
    queue = JobQueue(concurrency=1)
    full = samples.recipe_book_full()

    stuck = RecipeReaderFake(gate_at=4)  # 4回目の呼び出しで止まったまま（gate を渡さない）
    job = start(queue, stuck, full, 120)
    while stuck.calls < 4:
        await asyncio.sleep(0.005)
    before = job.snapshot()
    queue.cancel(job.id)  # DELETE /api/jobs/{id} と同じ
    after = await follow(queue, job)
    print(f"120ページの取り込み・{before['status']} {before['done']}/{before['total']} で取り消す → "
          f"{after}・result {job.result}・LLM {stuck.calls} 回")

    again = RecipeReaderFake()
    job = start(queue, again, full, 120)
    print(f"同じ文書をもう一度取り込む → {await follow(queue, job)}・LLM {again.calls} 回")

    counting = Counting(faulty)
    job = start(queue, counting, samples.recipe_book(), 3)
    print(f"3ページの取り込み・上流が 529 → {await follow(queue, job)}・LLM {counting.calls} 回")


async def run() -> None:
    async with httpx2.AsyncClient(base_url=MOCK) as c:
        await c.post("/_mock/reset")
    client = AsyncAnthropic()
    faulty_client = AsyncAnthropic(max_retries=0, default_headers={"x-mock-fault": "529"})
    mock, faulty = AnthropicProvider(client), AnthropicProvider(faulty_client)
    try:
        await receipts_part(mock, faulty)
        await jobs_part(faulty)
    finally:
        await client.close()
        await faulty_client.close()
    async with httpx2.AsyncClient(base_url=MOCK) as c:
        by_status = (await c.get("/_mock/stats")).json()["by_status"]
    print(f"mockllm が返した状態コード: {'・'.join(f'{k}×{v}' for k, v in sorted(by_status.items()))}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
