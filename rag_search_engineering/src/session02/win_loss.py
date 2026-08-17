#!/usr/bin/env python3
"""平均の裏側を見る：クエリ単位の勝ち負けを数える（セッション2 練習問題8）。

平均が 0.763 対 0.668 でも、その内訳が「全クエリで少しずつ負け」なのか
「9 割は互角で 1 割が壊滅」なのかで、次に打つ手はまったく変わる。

集計結果は reports/session02_winloss.json に保存する。
数字はここに印刷しない（自分の環境で開いて確かめてほしいため）。

    docker compose exec app python src/session02/win_loss.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

K = 10
ROOT = Path(__file__).resolve().parents[2]


def build_report(method: str, **params):
    chunks = chunk_all(load_docs(), method, **params)
    index = LexicalIndex().build(chunks)
    return evaluate(index, load_queries(), load_qrels(), k=K, label=f"bm25 / {method}")


def tally(rep_a, rep_b, metric: str) -> dict:
    """metric について、クエリ単位の勝ち負けを数える。"""
    a_win, b_win, tie = [], [], []
    for qid, row in rep_a.per_query.items():
        diff = row[metric] - rep_b.per_query[qid][metric]
        (a_win if diff > 1e-12 else b_win if diff < -1e-12 else tie).append(qid)
    return {
        "a_win": len(a_win), "b_win": len(b_win), "tie": len(tie),
        "a_win_queries": a_win, "b_win_queries": b_win,
    }


def main() -> None:
    rep_a = build_report("fixed", size=400, overlap=80)
    rep_b = build_report("heading", max_chars=600)
    result = {
        "a": rep_a.label, "b": rep_b.label, "k": K,
        "n_queries": len(rep_a.per_query),
        "recall": tally(rep_a, rep_b, "recall"),
        "ndcg": tally(rep_a, rep_b, "ndcg"),
    }
    out = ROOT / "reports" / "session02_winloss.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"比較したクエリ数: {result['n_queries']}")
    print(f"-> reports/{out.name}")


if __name__ == "__main__":
    main()
