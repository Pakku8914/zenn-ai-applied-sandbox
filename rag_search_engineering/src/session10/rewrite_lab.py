#!/usr/bin/env python3
"""ルールベースの書き換え（正規化・同義語辞書）の効果と副作用を測る。

    python src/session10/rewrite_lab.py

比較軸は Recall@10 に絞ってある。略語クエリの失敗は「到達不足」が大半なので、
まず「候補に到達したか」を見るのが筋だから（順位の指標は演習で足す）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from query_lab import (  # noqa: E402
    IndexSideSynonymIndex,
    RewriteRetriever,
    expand_query,
    expand_query_naive,
    failure_split,
)

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

TYPES = ("abbrev", "keyword", "multi_condition", "natural", "temporal")
REPORT_DIR = Path(__file__).resolve().parents[2] / "reports"


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)

    print("=== 1. 素朴な置換が壊れる2つのケース ===")
    for label, text in (("部分文字列に当たる", "パスワードの再設定"),
                        ("全角に当たらない", "ＭＦＡの手続きを知りたい")):
        print(f"[{label}]")
        print(f"  入力        : {text}")
        print(f"  素朴な置換  : {expand_query_naive(text)}")
        print(f"  正規化して展開: {expand_query(text)}")

    print("\n=== 2. 辞書が発火するクエリ ===")
    fired: dict[str, list[str]] = {}
    for q in queries:
        if expand_query(q.text) != q.text:
            fired.setdefault(q.type, []).append(q.query_id)
    for qtype, ids in sorted(fired.items()):
        head = " ".join(ids[:5]) + (" ..." if len(ids) > 5 else "")
        print(f"{qtype:<18}{len(ids):>4}件  {head}")
    print(f"発火した型: {sorted(fired)}  （対象外の型で発火したら、それは副作用）")

    index = LexicalIndex().build(chunks)
    rewriter = RewriteRetriever(index, expand_query)
    rep_base = evaluate(index, queries, qrels, k=10, label="bm25 / fixed")
    rep_syn = evaluate(rewriter, queries, qrels, k=10, label="bm25 / fixed + クエリ側展開")

    print("\n=== 3. クエリ側の展開の効果と副作用（Recall@10 / fixed(400/80) / 110クエリ）===")
    print(f"{'type':<18}{'n':>5}{'before':>10}{'after':>10}")
    for t in TYPES:
        b, a = rep_base.by_type[t], rep_syn.by_type[t]
        print(f"{t:<18}{int(b['n_queries']):>5}{b['recall']:>10.3f}{a['recall']:>10.3f}")
    print(f"{'ALL':<18}{int(rep_base.macro['n_queries']):>5}"
          f"{rep_base.macro['recall']:>10.3f}{rep_syn.macro['recall']:>10.3f}")
    print(f"書き換えが発火した検索: {rewriter.rewrites} 回")

    split_base = failure_split(index, queries, qrels, k=10, pool=100)
    split_syn = failure_split(rewriter, queries, qrels, k=10, pool=100)
    print(f"略語クエリの到達不足: {split_base['abbrev']['reach_loss']:.3f}"
          f" -> {split_syn['abbrev']['reach_loss']:.3f}")
    print(f"略語クエリの順位不足: {split_base['abbrev']['rank_loss']:.3f}"
          f" -> {split_syn['abbrev']['rank_loss']:.3f}")

    idx_side = IndexSideSynonymIndex().build(chunks)
    rep_idx = evaluate(idx_side, queries, qrels, k=10, label="bm25 + 索引側展開 / fixed")

    print("\n=== 4. 索引側（S05）とクエリ側（この章）の対比 ===")
    print("baseline=展開なし / index-side=索引側で展開 / query-side=クエリ側で展開")
    print(f"{'condition':<18}{'abbrev':>10}{'ALL':>10}")
    for label, rep in (("baseline", rep_base), ("index-side", rep_idx), ("query-side", rep_syn)):
        print(f"{label:<18}{rep.by_type['abbrev']['recall']:>10.3f}{rep.macro['recall']:>10.3f}")
    print(f"索引側の他の指標: nDCG@10={rep_idx.macro['ndcg']:.3f} "
          f"MRR={rep_idx.macro['mrr']:.3f} P@10={rep_idx.macro['precision']:.3f}")
    print(f"索引側で展開されたチャンク: {idx_side.expanded_chunks} / {len(chunks)}")

    rep_syn.to_json(REPORT_DIR / "s10_query_side_synonym.json")
    rep_idx.to_json(REPORT_DIR / "s10_index_side_synonym.json")
    print("\n-> reports/s10_query_side_synonym.json / reports/s10_index_side_synonym.json")


if __name__ == "__main__":
    main()
