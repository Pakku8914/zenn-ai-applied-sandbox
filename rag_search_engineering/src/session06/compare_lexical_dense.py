#!/usr/bin/env python3
"""BM25 と密ベクトル検索をクエリ型別に比べる（セッション6・問題6）。

全体平均（0.763 対 0.783）は「略語で大きく勝ち、自然文で少し負ける」の
打ち消し合いの結果でしかない。設計判断は型別に分解してから行う。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

COLLECTION = "minato_docs_fixed"


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)  # 2方式で同じチャンクを共有する

    lex = LexicalIndex().build(chunks)
    dense = DenseIndex(COLLECTION)  # 既存のコレクションを再利用する（埋め込みを再計算しない）
    if not dense.client.collection_exists(COLLECTION):
        print("コレクションを作成します（1分程度かかります）")
        dense.build(chunks)

    reports = [evaluate(lex, queries, qrels, k=10, label="bm25 / fixed"),
               evaluate(dense, queries, qrels, k=10, label="dense / fixed")]
    print()
    for rep in reports:
        print(rep.summary())

    print("\n=== クエリ型別 Recall@10 ===")
    types = sorted(reports[0].by_type)
    print(f"{'条件':<16}" + "".join(f"{t:>16}" for t in types))
    for rep in reports:
        print(f"{rep.label:<16}" + "".join(
            f"{rep.by_type[t]['recall']:>16.3f}" for t in types))

    # 自然文クエリを1件選び、両方式の上位10文書を目視する（適合文書に ★）
    target = next(q for q in queries if q.type == "natural")
    gold = {d for d, g in qrels.get(target.query_id, {}).items() if g >= 1}
    print(f"\n=== 目視: {target.query_id} 「{target.text}」 ===")
    for retriever, name in ((lex, "bm25 "), (dense, "dense")):
        ranked, seen = [], set()
        for hit in retriever.search(target.text, k=20):
            if hit.doc_id not in seen:
                seen.add(hit.doc_id)
                ranked.append(("★" if hit.doc_id in gold else "  ") + hit.doc_id)
        print(f"[{name}] {ranked[:10]}")


if __name__ == "__main__":
    main()
