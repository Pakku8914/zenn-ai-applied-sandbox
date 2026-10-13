"""問題4：引用の検証（セッション5・6）とレシートの文字との突き合わせ（セッション7）を、同じ正規化の目で比べる。

    docker compose exec api python -m src.review02.solutions.q4_match
"""

from __future__ import annotations

from src.review02 import samples
from src.review02.kit import (
    ReceiptItem, ReceiptRead, ReceiptText, check_citation, compare_with_text, extract_pages, extract_text,
    parse_receipt_text,
)

QUOTE = "調理時間 35分　4人分"  # recipe_pdf_ask が返す引用文（間に全角の空白がある）
CITATIONS = [
    ([29], 1, QUOTE),
    ([29], 1, "調理時間 ３５分 ４人分"),
    ([29], 1, "肉じゃがは4人分です"),
    ([29], 1, "4人分"),
    ([29], 2, QUOTE),
    ([11, 29, 84], 1, QUOTE),
    ([11, 29, 84], 2, QUOTE),
]
ITEMS = [("卵(10個入り)", 248), ("たまご", 248), ("牛乳", 282), ("キャベツ", 1072)]


def locate(page_texts: list[str], sent: list[int], page: int, quote: str) -> str:
    """page は送った PDF の中での番号。元の番号に戻してから、元のページで確かめる。"""
    if not 1 <= page <= len(sent):
        return "page_out_of_range（送っていないページ）"
    original = sent[page - 1]
    return f"元の {original} ページ・{check_citation(page_texts, original, quote).reason}"


def line_check(text: ReceiptText, name: str, price: int) -> str:
    """1品だけの読み取り結果を作る。店名・日付・合計は PDF と同じにして、行の突き合わせだけを見る。"""
    read = ReceiptRead(store="こんだてマート", purchased_at=text.purchased_at, total=text.total,
                       items=[ReceiptItem(name=name, quantity=1, price=price)])
    return "、".join(i["reason"] for i in compare_with_text(read, text)) or "一致"


def main() -> None:
    page_texts = extract_pages(samples.recipe_book_full())
    for sent, page, quote in CITATIONS:
        print(f"送った {sent} の {page} ページ目「{quote}」 → {locate(page_texts, sent, page, quote)}")
    text = parse_receipt_text(extract_text(samples.receipt_pdf()))
    assert text is not None
    for name, price in ITEMS:
        print(f"品目「{name}」{price}円 → {line_check(text, name, price)}")


if __name__ == "__main__":
    main()
