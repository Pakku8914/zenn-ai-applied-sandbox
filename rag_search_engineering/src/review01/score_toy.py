#!/usr/bin/env python3
"""3つのランキングを ragkit.eval で採点する（手計算の答え合わせ）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.eval import mrr, ndcg_at_k, precision_at_k, recall_at_k  # noqa: E402
from ragkit.models import Hit  # noqa: E402

QRELS = {"D1": 2, "D2": 2, "D3": 1, "D4": 1, "D5": 1}

RUNS = {
    "走査型": ["X1", "X2", "D1", "X3", "D2", "X4", "D3", "X5", "D4", "X6"],
    "一点型": ["D1", "D2", "X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8"],
    "畳み込み型": ["D1", "D1", "D2", "D1", "X1", "D2", "D1", "X1", "D2", "X1"],
}


def to_hits(doc_ids: list[str]) -> list[Hit]:
    # 同じ文書の別チャンクを表すので chunk_id は必ず別にする
    return [Hit(f"{d}#{i:03d}", d, 1.0 / i, "", {}) for i, d in enumerate(doc_ids, start=1)]


print(f"{'ランキング':<12}{'Recall@10':>11}{'P@10':>8}{'MRR':>8}{'nDCG@10':>9}{'文書数':>7}")
for label, docs in RUNS.items():
    hits = to_hits(docs)
    print(f"{label:<12}{recall_at_k(hits, QRELS, 10):>11.3f}{precision_at_k(hits, QRELS, 10):>8.3f}"
          f"{mrr(hits, QRELS):>8.3f}{ndcg_at_k(hits, QRELS, 10):>9.3f}"
          f"{len({h.doc_id for h in hits}):>7}")
