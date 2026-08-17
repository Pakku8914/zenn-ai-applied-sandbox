#!/usr/bin/env python3
"""ハイブリッド検索の設定を振って比較する。セッション8の実測値の出典。

「2つ混ぜれば必ず良くなる」わけではないことを数字で示すための道具。
候補数（candidates）と RRF の定数（rrf_k）、重みを振って挙動を見る。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.hybrid import HybridRetriever, minmax_fuse, rrf_fuse  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

K = 10


class TunedRRF:
    """rrf_k を変えて比較するための薄いラッパ。"""

    def __init__(self, retrievers, candidates: int, rrf_k: int) -> None:
        self.retrievers, self.candidates, self.rrf_k = retrievers, candidates, rrf_k

    def search(self, query: str, k: int = 10, filters: dict | None = None):
        lists = [r.search(query, k=self.candidates, filters=filters) for r in self.retrievers]
        return rrf_fuse(lists, k=k, rrf_k=self.rrf_k)


class WeightedMinMax:
    def __init__(self, retrievers, candidates: int, weights: list[float]) -> None:
        self.retrievers, self.candidates, self.weights = retrievers, candidates, weights

    def search(self, query: str, k: int = 10, filters: dict | None = None):
        lists = [r.search(query, k=self.candidates, filters=filters) for r in self.retrievers]
        return minmax_fuse(lists, weights=self.weights, k=k)


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)
    lex = LexicalIndex().build(chunks)
    dense = DenseIndex("minato_docs_fixed")
    if not dense.client.collection_exists("minato_docs_fixed"):
        print("コレクションを作成します（1分程度）")
        dense.build(chunks)

    print(evaluate(lex, queries, qrels, k=K, label="bm25 単体").summary())
    print(evaluate(dense, queries, qrels, k=K, label="dense 単体").summary())

    print("\n=== RRF: 候補数と rrf_k を振る ===")
    for candidates in (10, 20, 50):
        for rrf_k in (10, 60):
            r = TunedRRF([lex, dense], candidates=candidates, rrf_k=rrf_k)
            print(evaluate(r, queries, qrels, k=K,
                           label=f"rrf(cand={candidates}, k={rrf_k})").summary())

    print("\n=== min-max: 重みを振る（bm25 : dense）===")
    for weights in ([1.0, 1.0], [0.3, 1.0], [1.0, 0.3]):
        r = WeightedMinMax([lex, dense], candidates=50, weights=weights)
        print(evaluate(r, queries, qrels, k=K,
                       label=f"minmax(w={weights[0]}:{weights[1]})").summary())

    print("\n=== 略語クエリだけで見る（型別の勝ち負け）===")
    for label, r in [("bm25", lex), ("dense", dense),
                     ("rrf(cand=10,k=10)", TunedRRF([lex, dense], 10, 10)),
                     ("minmax(0.3:1.0)", WeightedMinMax([lex, dense], 50, [0.3, 1.0])),
                     ("rrf(cand=50,k=60)", HybridRetriever([lex, dense], 50, "rrf"))]:
        rep = evaluate(r, queries, qrels, k=K, label=label)
        abbrev = rep.by_type.get("abbrev", {})
        print(f"{label:<22} abbrev Recall@10={abbrev.get('recall', 0):.3f}  "
              f"全体 Recall@10={rep.macro['recall']:.3f}")


if __name__ == "__main__":
    main()
