#!/usr/bin/env python3
"""問題1の模範解答：トイコーパスから転置索引を組み立てる。

辞書（term -> df）とポスティングリスト（term -> {doc_id: tf}）を作り、
語ごとの df・idf と全体の avgdl を表示する。

    python src/session05/my_tiny_index.py
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

DOCS: dict[str, list[str]] = {
    "d1": ["有給休暇", "申請", "期限"],
    "d2": ["有給休暇", "有給休暇", "申請", "申請", "期限", "承認", "所属長", "総務部"],
    "d3": ["出張旅費", "精算", "期限"],
}


def build(docs: dict[str, list[str]]) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    postings: dict[str, dict[str, int]] = defaultdict(dict)
    doc_len: dict[str, int] = {}
    for doc_id, terms in docs.items():
        doc_len[doc_id] = len(terms)
        for term, tf in Counter(terms).items():
            postings[term][doc_id] = tf
    return postings, doc_len


def idf(postings: dict[str, dict[str, int]], n_docs: int, term: str) -> float:
    df = len(postings.get(term, {}))
    if df == 0:
        return 0.0  # 索引に無い語は例外にせず 0 点にする
    return math.log(1 + (n_docs - df + 0.5) / (df + 0.5))


def main() -> None:
    postings, doc_len = build(DOCS)
    n_docs = len(DOCS)
    avgdl = sum(doc_len.values()) / n_docs

    print(f"語彙数={len(postings)}  平均文書長={avgdl:.2f}")
    for term, plist in postings.items():
        print(f"  {term} df={len(plist)} idf={idf(postings, n_docs, term):.4f} "
              f"postings={dict(plist)}")
    print(f"索引に無い語: 交通費 df=0 idf={idf(postings, n_docs, '交通費'):.4f}")


if __name__ == "__main__":
    main()
