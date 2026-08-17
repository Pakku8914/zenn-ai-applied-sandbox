#!/usr/bin/env python3
"""k1 と b を走査して、実コーパスで順位がどう動くかを測る。

索引は1回だけ作り、k1・b は検索時のパラメータとして差し替える
（k1・b はスコアリングの係数なので、変えても索引を作り直す必要は無い）。

    python src/session05/tune_k1_b.py                 # Recall@10 の格子
    python src/session05/tune_k1_b.py --metric ndcg   # nDCG@10 の格子
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

K1S = (0.0, 0.6, 1.2, 2.0, 3.0)
BS = (0.0, 0.25, 0.5, 0.75, 1.0)
REPORT_DIR = Path(__file__).resolve().parents[2] / "reports"


def sweep(index: LexicalIndex, queries, qrels, metric: str) -> dict[tuple[float, float], float]:
    grid: dict[tuple[float, float], float] = {}
    for k1 in K1S:
        for b in BS:
            index.k1, index.b = k1, b
            rep = evaluate(index, queries, qrels, k=10, label=f"k1={k1} b={b}")
            grid[(k1, b)] = rep.macro[metric]
    return grid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metric", default="recall", choices=["recall", "ndcg", "mrr", "precision"])
    args = ap.parse_args()

    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    index = LexicalIndex().build(chunk_all(docs, "fixed", size=400, overlap=80))
    grid = sweep(index, queries, qrels, args.metric)

    print(f"=== {args.metric}@10（行: k1 / 列: b）===")
    print(f"{'k1|b':>6}" + "".join(f"{b:>9.2f}" for b in BS))
    for k1 in K1S:
        print(f"{k1:>6.1f}" + "".join(f"{grid[(k1, b)]:>9.3f}" for b in BS))

    best = max(grid.items(), key=lambda kv: (kv[1], -kv[0][0], -kv[0][1]))
    base = grid[(1.2, 0.75)]
    print(f"\n既定 k1=1.2 b=0.75 : {base:.3f}")
    print(f"最良 k1={best[0][0]} b={best[0][1]} : {best[1]:.3f}  (差 {best[1] - base:+.3f})")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"s05_tune_{args.metric}.json"
    out.write_text(json.dumps(
        {"metric": args.metric,
         "grid": [{"k1": k1, "b": b, "value": v} for (k1, b), v in grid.items()],
         "default": base, "best": {"k1": best[0][0], "b": best[0][1], "value": best[1]}},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out.relative_to(out.parents[1])}")


if __name__ == "__main__":
    main()
