#!/usr/bin/env python3
"""問題7：カテゴリで絞り込むとき、絞る場所を変えると候補が枯れることを測る。

  事前フィルタ: 検索器にフィルタを渡す（絞り込んだ世界で上位k件を埋める）
  事後フィルタ: 上位k件を取ってから絞る（枠が埋まらない・ゼロヒットになる）

チャンク方式によって枯れ方が変わるので、fixed と heading の両方で測ります。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fusion_lab import build_indexes, filter_run  # noqa: E402

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_qrels, load_queries  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

K = 10


def report(label: str, retriever, queries, qrels, docs_by_id) -> None:
    pre = filter_run(retriever, queries, qrels, docs_by_id, k=K, post=False)
    post = filter_run(retriever, queries, qrels, docs_by_id, k=K, post=True)
    for mode, row in (("事前フィルタ", pre), ("事後フィルタ", post)):
        print(f"{label + ' / ' + mode:<34}"
              f"平均返却件数={row['mean_hits']:>5.2f}  "
              f"ゼロヒット={int(row['zero_hits']):>3}件  "
              f"Recall@{K}={row['recall']:.3f}")


def main() -> None:
    docs, chunks_fixed, lex_fixed, dense = build_indexes()
    queries, qrels = load_queries(), load_qrels()
    docs_by_id = {d.doc_id: d for d in docs}
    lex_heading = LexicalIndex().build(chunk_all(docs, "heading", max_chars=600))

    print(f"絞り込み条件は「そのクエリの適合文書が最も多く属するカテゴリ」です"
          f"（対象 {sum(1 for q in queries if q.type != 'unanswerable')} クエリ）。\n")
    report("bm25 / fixed(400/80)", lex_fixed, queries, qrels, docs_by_id)
    report("bm25 / heading(600)", lex_heading, queries, qrels, docs_by_id)
    report("dense / fixed(400/80)", dense, queries, qrels, docs_by_id)

    print("\n1文書あたりのチャンク数が多い方式ほど、上位10件が少数の文書に集中します。")
    print("集中した先がフィルタで落ちると、事後フィルタでは残る候補がゼロになります。")


if __name__ == "__main__":
    main()
