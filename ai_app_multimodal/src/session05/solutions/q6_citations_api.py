"""問題6：citations 機能の応答（の形）を、本章の {answer, citations:[{page, quote}]} に変換して照合する。

    docker compose exec api python -m src.session05.solutions.q6_citations_api

SAMPLE_CONTENT は、citations を有効にしたときの応答の「形」を示すために手で書いた例（本物の応答ではない）。
"""

from __future__ import annotations

import json

from kondate.media import media_path
from src.session05.documents import check_citation, extract_pages

SAMPLE_CONTENT = [
    {"type": "text", "text": "レシピ集によると、"},
    {
        "type": "text",
        "text": "肉じゃがは4人分です",
        "citations": [{
            "type": "page_location",
            "cited_text": "R029　調理時間 35分　4人分　1人分 250kcal",
            "document_index": 0,
            "document_title": "recipe_book.pdf",
            "start_page_number": 1,
            "end_page_number": 2,  # この番号のページは含まない（1ページ目だけ）
        }],
    },
    {"type": "text", "text": "。"},
]


def to_own_format(content: list[dict]) -> dict:
    """text ブロックをつなげて answer に、page_location の引用を {page, quote} にする。"""
    answer = "".join(b["text"] for b in content if b["type"] == "text")
    citations = []
    for block in content:
        for c in block.get("citations") or []:
            if c["type"] != "page_location":  # 文字位置（char_location）などは PDF のページに当てはまらない
                continue
            pages = list(range(c["start_page_number"], c["end_page_number"]))  # 終わりの番号は含まない
            citations.append({"page": pages[0], "quote": c["cited_text"].strip(), "pages": pages})
    return {"answer": answer, "citations": citations}


def verify(own: dict, page_texts: list[str]) -> list[str]:
    """複数ページにまたがる引用は、またがったページの文字をつなげて照合する。"""
    results = []
    for c in own["citations"]:
        joined = ["".join(page_texts[p - 1] for p in c["pages"])]
        results.append(check_citation(joined, 1, c["quote"]).reason)
    return results


def main() -> None:
    own = to_own_format(SAMPLE_CONTENT)
    pages = extract_pages(media_path("recipe_book.pdf").read_bytes())
    print(f"answer: {own['answer']}")
    print(f"citations: {json.dumps([{'page': c['page'], 'quote': c['quote']} for c in own['citations']], ensure_ascii=False)}")
    for c, reason in zip(own["citations"], verify(own, pages), strict=True):
        print(f"照合: {c['page']}ページ → {reason}")


if __name__ == "__main__":
    main()
