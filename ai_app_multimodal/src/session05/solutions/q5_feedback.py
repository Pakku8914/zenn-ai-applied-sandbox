"""問題5：引用が確かめられなかった理由を診断し、その理由を添えて1回だけ聞き直す。

    docker compose exec api python -m src.session05.solutions.q5_feedback
"""

from __future__ import annotations

import asyncio
import json

from pydantic import ValidationError

from kondate.llm import ChatRequest, ChatResult, FakeProvider, LLMProvider, Usage
from kondate.media import media_path
from src.session05.app import ANSWER_SCHEMA, SYSTEM_PROMPT, DocumentAnswer
from src.session05.documents import MIN_QUOTE_CHARS, extract_pages, normalize, pdf_block

MAX_ATTEMPTS = 2
FEEDBACK_HEAD = "次の引用を文書の中で確かめられませんでした。文書のとおりに直して、もう一度答えてください。"
QUOTE = "調理時間 35分　4人分"


def diagnose(page_texts: list[str], page: int, quote: str) -> tuple[str, int | None]:
    """(理由, 実際に見つかったページ) を返す。理由は ok / too_short / wrong_page / page_out_of_range / not_found。"""
    q = normalize(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return "too_short", None
    found = [i for i, text in enumerate(page_texts, 1) if q in normalize(text)]
    if page in found:
        return "ok", page
    if found:
        return "wrong_page", found[0]
    if not 1 <= page <= len(page_texts):
        return "page_out_of_range", None
    return "not_found", None


def describe(page: int, quote: str, reason: str, actual: int | None, total: int) -> str:
    head = f"{page}ページ「{quote}」："
    return head + {
        "too_short": f"短すぎて根拠になりません（{MIN_QUOTE_CHARS}文字以上で引用してください）",
        "wrong_page": f"このページにはありません（{actual}ページにあります）",
        "page_out_of_range": f"文書は {total} ページまでです",
        "not_found": "文書のどのページにも見つかりません",
    }[reason]


async def ask_with_feedback(llm: LLMProvider, raw: bytes, page_texts: list[str], question: str):
    """(答え または None, 診断の記録 [(回, ページ, 理由, 実際のページ)]) を返す。"""
    messages: list[dict] = [{"role": "user", "content": [pdf_block(raw), {"type": "text", "text": question}]}]
    log: list[tuple[int, int, str, int | None]] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = await llm.complete(ChatRequest(messages=list(messages), system=SYSTEM_PROMPT, output_schema=ANSWER_SCHEMA))
        problems: list[str] = []
        try:
            answer = DocumentAnswer.model_validate_json(result.text)
        except ValidationError:
            answer = None
            problems.append("応答が指定した JSON の形になっていませんでした")
        else:
            if not answer.citations:
                problems.append("引用が1件もありませんでした。根拠にした文を必ず引用してください")
            for c in answer.citations:
                reason, actual = diagnose(page_texts, c.page, c.quote)
                log.append((attempt, c.page, reason, actual))
                if reason != "ok":
                    problems.append(describe(c.page, c.quote, reason, actual, len(page_texts)))
        if not problems:
            return answer, log
        # 前回の応答（assistant）と、何が駄目だったか（user）を足して聞き直す。最後は user なので prefill にならない
        messages += [
            {"role": "assistant", "content": result.text},
            {"role": "user", "content": FEEDBACK_HEAD + "\n" + "\n".join(f"- {p}" for p in problems)},
        ]
    return None, log


def answer_json(page: int) -> str:
    return json.dumps({"answer": "肉じゃがは4人分です。", "citations": [{"page": page, "quote": QUOTE}]}, ensure_ascii=False)


def demo_provider() -> FakeProvider:
    """1回目はページ違い、2回目は正しいページを返す偽物。"""
    return FakeProvider([ChatResult(answer_json(p), [], "end_turn", Usage(4888, 38)) for p in (2, 1)])


async def main() -> None:
    raw = media_path("recipe_book.pdf").read_bytes()
    llm = demo_provider()
    answer, log = await ask_with_feedback(llm, raw, extract_pages(raw), "肉じゃがは何人分ですか？")
    for attempt, page, reason, actual in log:
        note = f"（実際は{actual}ページ）" if reason == "wrong_page" else ""
        print(f"{attempt}回目：{page}ページ → {reason}{note}")
    second = llm.requests[1].messages
    print(f"再試行で送ったメッセージ：{len(second)}件（{' → '.join(m['role'] for m in second)}）")
    print(f"フィードバック：{second[-1]['content'].splitlines()[1]}")
    print(f"結果：{answer.answer if answer else '確かめられませんでした'}")


if __name__ == "__main__":
    asyncio.run(main())
