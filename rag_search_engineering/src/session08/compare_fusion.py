#!/usr/bin/env python3
"""セッション8：融合方式を実データで比較する。

「2つ混ぜれば良くなる」が成り立たない条件を、まず自分の手で出すためのスクリプト。
密ベクトルのコレクションは既存のものを再利用する（無ければ1回だけ作る）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

from fuse import FusionRetriever, my_minmax_fuse, my_rrf_fuse  # noqa: E402

COLLECTION = "minato_docs_fixed"
K = 10


def line(label: str, rep) -> None:
    """実測表と突き合わせられる列だけを出す（P@10 は eval_matrix.py 側で見る）。"""
    abbrev = rep.by_type.get("abbrev", {}).get("recall", 0.0)
    print(f"{label:<24}Recall@{rep.k}={rep.macro['recall']:.3f} "
          f"nDCG@{rep.k}={rep.macro['ndcg']:.3f} MRR={rep.macro['mrr']:.3f} "
          f"abbrev={abbrev:.3f}")


def build():
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)
    lex = LexicalIndex().build(chunks)
    dense = DenseIndex(COLLECTION)
    if not dense.client.collection_exists(COLLECTION):
        print("コレクションを作成します（1分程度かかります）")
        dense.build(chunks)
    return lex, dense, queries, qrels


def main() -> None:
    lex, dense, queries, qrels = build()

    print("=== 融合方式の比較（fixed(400/80) / k=10 / 回答可能な110クエリ）===")
    line("bm25", evaluate(lex, queries, qrels, k=K))
    line("dense", evaluate(dense, queries, qrels, k=K))

    for candidates, rrf_k in ((50, 60), (10, 10)):
        r = FusionRetriever([lex, dense], candidates=candidates, fuse=my_rrf_fuse, rrf_k=rrf_k)
        line(f"rrf(cand={candidates}, rrf_k={rrf_k})", evaluate(r, queries, qrels, k=K))

    for w in ([1.0, 1.0], [0.3, 1.0]):
        r = FusionRetriever([lex, dense], candidates=50, fuse=my_minmax_fuse, weights=w)
        line(f"minmax({w[0]}:{w[1]})", evaluate(r, queries, qrels, k=K))


if __name__ == "__main__":
    main()
