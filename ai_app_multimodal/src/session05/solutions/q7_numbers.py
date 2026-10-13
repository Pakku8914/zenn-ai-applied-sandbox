"""問題7：答えに出てくる数が、引用文で裏付けられているかを確かめる（数のグラウンディング）。

    docker compose exec api python -m src.session05.solutions.q7_numbers
"""

from __future__ import annotations

import json
import re
import unicodedata

from kondate.media import media_path
from src.session05.app import DocumentAnswer, grounded_answer
from src.session05.documents import extract_pages

NUMBER = re.compile(r"\d+(?:\.\d+)?")
PAGE_REF = re.compile(r"\d+\s*ページ")  # 「1ページによると」の 1 は答えの中身ではない
QUOTE = "調理時間 35分　4人分"
CASES = [
    "肉じゃがは4人分です。",
    "肉じゃがは2人分です。",
    "肉じゃがは4人分で、35分で作れます。",
    "肉じゃがは４人分です。",
    "肉じゃがは5人分です。",
    "1ページによると、肉じゃがは4人分です。",
]


def numbers(text: str) -> set[str]:
    """数を「文字列の部分」ではなく「数のまとまり」として取り出す（35 の中の 5 を 5 と数えない）。"""
    return set(NUMBER.findall(unicodedata.normalize("NFKC", text)))


def ungrounded_numbers(answer: str, quotes: list[str]) -> list[str]:
    in_answer = numbers(PAGE_REF.sub("", unicodedata.normalize("NFKC", answer)))
    in_quotes = set().union(*(numbers(q) for q in quotes))
    return sorted(in_answer - in_quotes)


def strict_grounded_answer(text: str, page_texts: list[str]) -> DocumentAnswer | None:
    """本文の grounded_answer（形と引用の実在）に、数の裏付けの検査を足したもの。"""
    answer = grounded_answer(text, page_texts)
    if answer is None or ungrounded_numbers(answer.answer, [c.quote for c in answer.citations]):
        return None
    return answer


def verdicts() -> list[str]:
    pages = extract_pages(media_path("recipe_book.pdf").read_bytes())
    out = []
    for answer in CASES:
        text = json.dumps({"answer": answer, "citations": [{"page": 1, "quote": QUOTE}]}, ensure_ascii=False)
        missing = ungrounded_numbers(answer, [QUOTE])
        ok = strict_grounded_answer(text, pages) is not None
        out.append("裏付けあり" if ok else f"裏付けなし（{'・'.join(missing)}）")
    return out


def main() -> None:
    for answer, verdict in zip(CASES, verdicts(), strict=True):
        print(f"「{answer}」→ {verdict}")


if __name__ == "__main__":
    main()
