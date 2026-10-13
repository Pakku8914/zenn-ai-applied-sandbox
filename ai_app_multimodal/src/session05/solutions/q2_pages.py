"""問題2：ページごとに文字が抜けるかを調べ、送り方（抜き出した文字か PDF のままか）の候補を決める。

    docker compose exec api python -m src.session05.solutions.q2_pages
"""

from __future__ import annotations

from kondate.media import media_path
from src.session05.compare import scanned_pdf
from src.session05.documents import extract_pages, normalize

MIN_TEXT_CHARS = 20  # 空白を除いてこれ未満なら「文字が取れていない」とみなす（ページ番号だけのページなど）


def page_report(raw: bytes) -> list[tuple[int, bool]]:
    """[(ページ番号, 文字が取れたか)] を返す。"""
    return [(i, len(normalize(t)) >= MIN_TEXT_CHARS) for i, t in enumerate(extract_pages(raw), 1)]


def suggest(raw: bytes, needs_layout: bool = False) -> str:
    """"text"（抜き出した文字で足りる）か "pdf"（PDF のまま送る）を返す。"""
    if needs_layout:  # 表の並び・図・写真を読ませたい質問は、文字だけでは答えられない
        return "pdf"
    return "text" if all(ok for _, ok in page_report(raw)) else "pdf"


LABEL = {"text": "抜き出した文字（text）", "pdf": "PDF のまま（base64）"}


def main() -> None:
    book = media_path("recipe_book.pdf").read_bytes()
    scan = scanned_pdf()
    for name, raw in (("recipe_book.pdf", book), ("画像だけの PDF", scan)):
        for page, ok in page_report(raw):
            print(f"{name} {page}ページ：{'文字あり' if ok else '文字なし（画像だけの可能性）'}")
        print(f"→ 送り方の候補：{LABEL[suggest(raw)]}")
    print(f"recipe_book.pdf（表や図を読ませたい質問）→ 送り方の候補：{LABEL[suggest(book, needs_layout=True)]}")


if __name__ == "__main__":
    main()
