#!/usr/bin/env python3
"""表を行文章化し、行を検索単位にして引いてみる。

行文章化した仮想チャンクは本文チャンクとは別の索引に載せる。トークナイザは
文字 bi-gram を使う（型番 `MN-Book15` のような文字列を落とさないため。セッション5参照）。

    python src/session15/row_sentences.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.corpus import load_docs  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.models import Chunk  # noqa: E402
from table_tools import row_chunks  # noqa: E402

QUERIES = [
    "役職手当の月額はいくらですか",
    "MN-Book15のメモリは",
    "大会議室の定員は",
]


def all_row_chunks() -> list[Chunk]:
    return [c for doc in load_docs() for c in row_chunks(doc)]


def build_row_index(mode: str = "bigram") -> tuple[LexicalIndex, list[Chunk]]:
    rows = all_row_chunks()
    return LexicalIndex(mode=mode).build(rows), rows


def main() -> None:
    index, rows = build_row_index()
    print(f"行チャンク: {len(rows)} 件（表 {len({(c.doc_id, c.meta['table_no']) for c in rows})} 個ぶん）")

    print("\n--- 行文章化の例（各種手当の支給手順書（第1版）の一覧）---")
    for c in rows:
        if c.doc_id == "DOC-0094":
            print(f"{c.chunk_id}: {c.text}")

    for q in QUERIES:
        # visibility=all だけを対象にする（管理職限定の表を一般社員に見せない。セッション13）
        hits = index.search(q, k=3, filters={"visibility": "all"})
        print(f"\n--- クエリ「{q}」---")
        for rank, h in enumerate(hits, start=1):
            print(f"{rank}. {h.chunk_id} score={h.score:.3f} {h.text}")


if __name__ == "__main__":
    main()
