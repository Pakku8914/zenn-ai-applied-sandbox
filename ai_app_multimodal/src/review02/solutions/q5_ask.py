"""問題5：120ページと3ページの文書に質問し、ページ選択・キャッシュ・再試行で usage がどう変わるかを確かめる。

    docker compose exec api python -m src.review02.solutions.q5_ask
"""

from __future__ import annotations

import asyncio

import anthropic
import httpx2
from anthropic import AsyncAnthropic

from kondate.llm import AnthropicProvider, ChatRequest, LLMProvider, Usage
from kondate.settings import get_settings
from src.review02 import samples
from src.review02.kit import (
    ANSWER_SCHEMA, DOC_MSG_UPSTREAM, MAX_ATTEMPTS, MSG_UNGROUNDED, SYSTEM_PROMPT,
    Counting, Doc, Outcome, Rejected, cached, choose_pages, failure, grounded_answer, load_doc,
    pdf_block, selected_pdf, sum_usage,
)

settings = get_settings()
QUESTION = "肉じゃがは何人分ですか？"


async def ask(llm: LLMProvider, doc: Doc, question: str, pages: list[int] | None = None,
              use_cache: bool = True) -> Outcome:
    try:
        sent = choose_pages(doc, question, pages)  # セッション6：決められなければ LLM を呼ばずに 422
    except Rejected as e:
        return failure(e.status, e.type, e.message)
    data = await selected_pdf(doc, sent)
    block = cached(pdf_block(data)) if use_cache else pdf_block(data)
    req = ChatRequest(
        messages=[{"role": "user", "content": [block, {"type": "text", "text": question}]}],
        system=SYSTEM_PROMPT, output_schema=ANSWER_SCHEMA, max_tokens=settings.llm_max_tokens,
    )
    used: list[Usage] = []
    for _ in range(MAX_ATTEMPTS):  # セッション5：引用を確かめられなければ1回だけ再試行
        try:
            result = await llm.complete(req)
        except anthropic.APIError:
            return failure(503, "upstream_unavailable", DOC_MSG_UPSTREAM, sum_usage(used))
        used.append(result.usage)
        answer = grounded_answer(result.text, doc.page_texts, sent)
        if answer is not None:
            body = {"answer": answer.answer, "citations": [c.model_dump() for c in answer.citations]}
            return Outcome(200, body, sum_usage(used))
    return failure(502, "invalid_output", MSG_UNGROUNDED, sum_usage(used))


def show(o: Outcome, calls: int) -> str:
    if o.status == 200:
        head = f"200 引用 {o.body['citations'][0]['page']} ページ"
    else:
        head = f"{o.status} {o.body['error']['type']}「{o.body['error']['message']}」"
    u = o.usage
    return (f"{head}・usage {u.input_tokens}/{u.output_tokens}・"
            f"キャッシュ 作成 {u.cache_creation_input_tokens}／読み出し {u.cache_read_input_tokens}・LLM {calls} 回")


async def run() -> None:
    async with httpx2.AsyncClient(base_url=settings.mockllm_url) as c:
        await c.post("/_mock/reset")  # 統計とプロンプトキャッシュを消す
    full, small = load_doc(samples.recipe_book_full()), load_doc(samples.recipe_book())
    cases = [
        ("120ページ・pages=[29]", full, QUESTION, [29], True),
        ("120ページ・pages なし", full, QUESTION, None, True),
        ("120ページ・pages=[29, 29]", full, QUESTION, [29, 29], True),
        ("120ページ・pages=[84, 29, 11]", full, QUESTION, [84, 29, 11], True),
        ("120ページ・pages なし・「おすすめはどれですか？」", full, "おすすめはどれですか？", None, True),
        ("120ページ・pages=1〜21", full, QUESTION, list(range(1, 22)), True),
        ("3ページ・pages なし", small, QUESTION, None, True),
        ("3ページ・キャッシュの印なし（セッション5の作り）", small, QUESTION, None, False),
    ]
    client = AsyncAnthropic()
    try:
        for label, doc, question, pages, use_cache in cases:
            llm = Counting(AnthropicProvider(client))
            o = await ask(llm, doc, question, pages, use_cache)
            print(f"{label} → {show(o, llm.calls)}")
    finally:
        await client.close()
    async with httpx2.AsyncClient(base_url=settings.mockllm_url) as c:
        by_scenario = (await c.get("/_mock/stats")).json()["by_scenario"]
    print(f"mockllm のシナリオ: {'・'.join(f'{k}×{v}' for k, v in sorted(by_scenario.items()))}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
