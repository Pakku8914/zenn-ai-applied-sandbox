#!/usr/bin/env python3
"""10 クエリ × 2 手法の小さな検索結果を評価する（セッション2 本文・練習問題6）。

手で計算した答えと突き合わせるための実行スクリプト。

    docker compose exec app python src/session02/eval_toy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.eval import evaluate  # noqa: E402
from toy_runs import QIDS, QRELS, QUERIES, RUNS_A, RUNS_B, ToyRetriever  # noqa: E402

K = 5

rep_a = evaluate(ToyRetriever(RUNS_A), QUERIES, QRELS, k=K, label="手法A")
rep_b = evaluate(ToyRetriever(RUNS_B), QUERIES, QRELS, k=K, label="手法B")

print(f"=== 10クエリ × 2手法（k={K}）===")
for name, key in (("Recall@5", "recall"), ("P@5", "precision"),
                  ("MRR", "mrr"), ("nDCG@5", "ndcg")):
    print(f"{name:<10} A={rep_a.macro[key]:.3f}  B={rep_b.macro[key]:.3f}")

print("\n--- クエリ別 nDCG@5 ---")
for qid in QIDS:
    print(f"{qid}  A={rep_a.per_query[qid]['ndcg']:.3f}  B={rep_b.per_query[qid]['ndcg']:.3f}")


def win_loss(key: str) -> tuple[int, int, int]:
    """クエリ単位で A と B のどちらが勝ったかを数える。"""
    a = sum(1 for qid in QIDS if rep_a.per_query[qid][key] > rep_b.per_query[qid][key])
    b = sum(1 for qid in QIDS if rep_a.per_query[qid][key] < rep_b.per_query[qid][key])
    return a, b, len(QIDS) - a - b


print("\n--- クエリ別の勝ち負け ---")
for name, key in (("Recall@5", "recall"), ("MRR", "mrr"), ("nDCG@5", "ndcg")):
    a, b, tie = win_loss(key)
    print(f"{name:<10} A勝ち={a}  B勝ち={b}  引き分け={tie}")
