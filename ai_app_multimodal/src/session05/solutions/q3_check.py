"""問題3：引用文がそのページに本当にあるかを確かめる関数を、自分で書く。

    docker compose exec api python -m src.session05.solutions.q3_check
"""

from __future__ import annotations

import re
import unicodedata

from kondate.media import media_path
from src.session05.documents import extract_pages

MIN_QUOTE_CHARS = 6
CASES = [
    (1, "R029　調理時間 35分"),
    (1, "R029 調理時間35分"),
    (1, "肉じゃが"),
    (0, "R029　調理時間 35分"),
    (1, "調理時間 25分　2人分"),
    (2, "調理時間 25分　2人分"),
]


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def check_quote(page_texts: list[str], page: int, quote: str) -> str:
    q = normalize(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return "too_short"
    if not 1 <= page <= len(page_texts):
        return "page_out_of_range"
    return "ok" if q in normalize(page_texts[page - 1]) else "not_found"


def results() -> list[str]:
    pages = extract_pages(media_path("recipe_book.pdf").read_bytes())  # 抽出は1回だけ。引用ごとに読み直さない
    return [check_quote(pages, p, q) for p, q in CASES]


def main() -> None:
    for (page, quote), reason in zip(CASES, results(), strict=True):
        print(f"{page}ページ「{quote}」→ {reason}")


if __name__ == "__main__":
    main()
