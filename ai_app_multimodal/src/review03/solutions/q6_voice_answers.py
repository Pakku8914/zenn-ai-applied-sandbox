"""問題6：声で届いた質問（音声認識の結果）で120ページのレシピ本に聞き（セッション5・6・8）、
答え・レシートと食材の要確認（セッション4・7）を、読み上げる文にする（セッション9）。

    docker compose exec api python -m src.review03.solutions.q6_voice_answers
"""

from __future__ import annotations

import asyncio

import anthropic
import anyio
import httpx2
from anthropic import AsyncAnthropic

from kondate.clock import FixedClock
from kondate.llm import AnthropicProvider, ChatRequest, LLMProvider, Usage
from kondate.settings import get_settings
from src.review03 import samples
from src.review03.kit import (
    ANSWER_SCHEMA, ASK_MAX_PAGES, MAX_ATTEMPTS, SYSTEM_PROMPT, Counting, Doc, DocumentAnswer, check_receipt,
    find_issues, fold_kana, grounded_answer, load_doc, normalize, pdf_block, selected_pdf, split_sentences, sum_usage,
)

settings = get_settings()
TODAY = FixedClock().now().date()   # 2026-10-02

# 画面の固定文は「pages で…」のように操作を指すので、声では別の言い方にする
VOICE = {
    422: "どのレシピのことか分かりませんでした。料理の名前を入れて、もう一度聞いてください。",
    502: "本の中で根拠を確かめられませんでした。別の聞き方で試してください。",
    503: "いまは本を読めませんでした。少し待ってから聞いてください。",
}
QUESTIONS = [
    ("肉じゃがは何人分ですか？", "両側"),
    ("肉ジャガは何人分ですか？", "なし"),
    ("肉ジャガは何人分ですか？", "両側"),
    ("ハンバーグは何人分ですか？", "質問だけ"),
    ("ハンバーグは何人分ですか？", "両側"),
]


def guess(doc: Doc, question: str, fold: str) -> list[int]:
    """見出しの索引から読むページを当てる（セッション6）。fold で、カタカナをひらがなに寄せる側を選ぶ（セッション8）。"""
    q = normalize(question)
    if fold in ("質問だけ", "両側"):
        q = fold_kana(q)

    def name(h) -> str:
        return fold_kana(h.name) if fold == "両側" else h.name

    return sorted({h.page for h in doc.index if h.name and name(h) in q})


async def ask(llm: LLMProvider, doc: Doc, question: str, pages: list[int]) -> tuple[int, DocumentAnswer | None, Usage]:
    """選んだページだけを送り、引用を元のページで確かめる（セッション5・6）。キャッシュの印は付けない。"""
    part = await selected_pdf(doc, pages)
    req = ChatRequest(
        messages=[{"role": "user", "content": [pdf_block(part), {"type": "text", "text": question}]}],
        system=SYSTEM_PROMPT, output_schema=ANSWER_SCHEMA, max_tokens=settings.llm_max_tokens,
    )
    used: list[Usage] = []
    for _ in range(MAX_ATTEMPTS):
        try:
            result = await llm.complete(req)
        except anthropic.APIError:
            return 503, None, sum_usage(used)
        used.append(result.usage)
        if (answer := grounded_answer(result.text, doc.page_texts, pages)) is not None:
            return 200, answer, sum_usage(used)
    return 502, None, sum_usage(used)


def answer_speech(status: int, answer: DocumentAnswer | None) -> str:
    if status != 200:
        return VOICE[status]
    return f"{answer.answer}根拠は{answer.citations[0].page}ページにあります。"


def issues_speech(issues: list[dict]) -> str:
    """セッション4（食材）とセッション7（レシート）の issues のどちらにも使える。"""
    if not issues:
        return "要確認はありません。"
    parts = [f"要確認が{len(issues)}件あります。"]
    for i in issues:
        head = f"{i['name']}は、" if i["name"] else ""
        parts.append(head + i["message"].rstrip("。") + "。")
    return "".join(parts)


def spoken(text: str) -> str:
    sentences = split_sentences(text)
    return f"読み上げ {len(sentences)} 文: {'／'.join(sentences)}"


async def run() -> None:
    async with httpx2.AsyncClient(base_url=settings.mockllm_url) as c:
        await c.post("/_mock/reset")
    doc = await anyio.to_thread.run_sync(load_doc, samples.recipe_book_full())
    client = AsyncAnthropic()
    try:
        for question, fold in QUESTIONS:
            llm = Counting(AnthropicProvider(client))
            pages = guess(doc, question, fold)
            if 1 <= len(pages) <= ASK_MAX_PAGES:
                status, answer, usage = await ask(llm, doc, question, pages)
            else:
                status, answer, usage = 422, None, Usage(0, 0)   # LLM を呼ばずに断る
            print(f"{question}（かなの寄せ方: {fold}） → pages {pages or 'なし'}・{status}・"
                  f"usage {usage.input_tokens}/{usage.output_tokens}・LLM {llm.calls} 回 → "
                  f"{spoken(answer_speech(status, answer))}")
    finally:
        await client.close()

    receipt = check_receipt(samples.receipt_read(total=1000), TODAY)
    print(f"レシート（合計が合わない） → 要確認 {len(receipt)} 件 → {spoken(issues_speech(receipt))}")
    fridge = find_issues(samples.fridge_items())
    print(f"冷蔵庫の食材（鶏ムネ肉・にんじん） → 要確認 {len(fridge)} 件 → {spoken(issues_speech(fridge))}")

    async with httpx2.AsyncClient(base_url=settings.mockllm_url) as c:
        by_scenario = (await c.get("/_mock/stats")).json()["by_scenario"]
    print(f"mockllm のシナリオ: {'・'.join(f'{k}×{v}' for k, v in sorted(by_scenario.items()))}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
