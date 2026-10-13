"""問題2：見出しの索引から、キーワードで読むページに当たりを付ける（表記ゆれも吸収する）。

    docker compose exec api python -m src.session06.solutions.q2_pick
"""

from __future__ import annotations

from kondate.media import media_path
from src.session06.documents import extract_pages, normalize
from src.session06.pages import ASK_MAX_PAGES, Heading, build_index

SYNONYMS = {"みそ": ["味噌"], "味噌": ["みそ"]}  # 同じものを指す書き方の違い
CASES = [["生姜焼き"], ["照り焼き", "唐揚げ"], ["みそ汁"], ["みそ"], ["うどん"]]


def expand(keywords: list[str]) -> list[str]:
    out: list[str] = []
    for k in keywords:
        for w in [k, *SYNONYMS.get(k, [])]:
            if (n := normalize(w)) and n not in out:
                out.append(n)
    return out


def pick_pages(index: list[Heading], keywords: list[str]) -> list[int]:
    """料理名にキーワードのどれかを含むページ（昇順）。20ページを超えたら絞り込みを促す。"""
    words = expand(keywords)
    pages = sorted({h.page for h in index if any(w in h.name for w in words)})
    if len(pages) > ASK_MAX_PAGES:
        raise ValueError(f"{len(pages)} ページ当たりました。キーワードを絞ってください")
    return pages


def load_index() -> list[Heading]:
    return build_index(extract_pages(media_path("recipe_book_full.pdf").read_bytes()))


def main() -> None:
    index = load_index()
    for keywords in CASES:
        print(f"{keywords} → {pick_pages(index, keywords)}")
    try:
        pick_pages(index, ["肉"])
    except ValueError:
        print("['肉'] → 20ページを超えるので ValueError")


if __name__ == "__main__":
    main()
