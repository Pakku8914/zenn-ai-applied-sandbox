#!/usr/bin/env python3
"""問題5：素朴なハイブリッド検索が単体に負けるのを再現し、設定を変えて回復させる。

密ベクトルのコレクション（minato_docs_fixed）は既存のものを再利用します。
7条件 × 110クエリを回すので、1分前後かかります。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fusion_lab import SumRetriever, build_indexes  # noqa: E402

from ragkit.corpus import load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.hybrid import HybridRetriever  # noqa: E402


def build_conditions(lex, dense) -> dict[str, object]:
    """比較する7条件。重みは [bm25, dense] の順で渡す。"""
    return {
        "bm25 単体": lex,
        "dense 単体": dense,
        "単純加算(候補50)": SumRetriever([lex, dense], candidates=50),
        "rrf(候補50, rrf_k=60)": HybridRetriever([lex, dense], 50, "rrf"),
        "rrf(候補10, rrf_k=60)": HybridRetriever([lex, dense], 10, "rrf"),
        "minmax(候補50, 1.0:1.0)": HybridRetriever([lex, dense], 50, "minmax", [1.0, 1.0]),
        "minmax(候補50, 0.3:1.0)": HybridRetriever([lex, dense], 50, "minmax", [0.3, 1.0]),
    }


def run_all(lex, dense, queries, qrels, k: int = 10) -> dict[str, object]:
    """全条件を1回ずつ評価する。per_query を残しておくと後から部分集合を作れる。"""
    return {
        name: evaluate(r, queries, qrels, k=k, label=name)
        for name, r in build_conditions(lex, dense).items()
    }


def print_table(reps: dict[str, object]) -> None:
    print(f"{'条件':<26}{'Recall@10':>11}{'nDCG@10':>10}{'MRR':>8}"
          f"{'abbrev':>9}{'natural':>9}")
    for name, rep in reps.items():
        m = rep.macro
        by = rep.by_type
        print(f"{name:<26}{m['recall']:>11.3f}{m['ndcg']:>10.3f}{m['mrr']:>8.3f}"
              f"{by['abbrev']['recall']:>9.3f}{by['natural']['recall']:>9.3f}")


def main() -> None:
    _, _, lex, dense = build_indexes()
    queries, qrels = load_queries(), load_qrels()
    reps = run_all(lex, dense, queries, qrels)
    print_table(reps)

    base = max(reps["bm25 単体"].macro["recall"], reps["dense 単体"].macro["recall"])
    print(f"\n単体の最良は Recall@10 = {base:.3f} です。これを下回る条件を並べます。")
    for name, rep in reps.items():
        if name.endswith("単体"):
            continue
        diff = rep.macro["recall"] - base
        verdict = "負けている" if diff < 0 else "勝っている"
        print(f"  {name:<26}{rep.macro['recall']:.3f}（{diff:+.3f}）{verdict}")


if __name__ == "__main__":
    main()
