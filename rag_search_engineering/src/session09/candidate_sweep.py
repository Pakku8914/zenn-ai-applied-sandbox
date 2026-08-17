#!/usr/bin/env python3
"""候補数を振って「精度の伸び」と「かかった時間」を同じ表で見る。

リランクは1クエリあたり数百ミリ秒〜数秒かかるので、既定では少数のクエリだけを回す。
全 110 クエリでの集計値は tools/bench_rerank.py で取る（3分ほどかかる）。

実行:  docker compose exec app python src/session09/candidate_sweep.py
      docker compose exec app python src/session09/candidate_sweep.py natural 6
      docker compose exec app python src/session09/candidate_sweep.py all 10
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import answerable, dense_index, load_all  # noqa: E402

from ragkit.eval import evaluate  # noqa: E402
from ragkit.rerank import CrossEncoderReranker, RerankRetriever  # noqa: E402

CANDIDATES = (10, 20, 50)
K = 10


def row(label: str, rep, seconds: float, n: int) -> str:
    m = rep.macro
    return (f"{label:<26}{m['recall']:>9.3f}{m['ndcg']:>9.3f}{m['mrr']:>8.3f}"
            f"{m['precision']:>8.3f}{seconds:>9.1f}{seconds / n * 1000:>12.0f}")


def main() -> None:
    qtype = sys.argv[1] if len(sys.argv) > 1 else "multi_condition"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 8

    _docs, queries, qrels, chunks = load_all()
    pool = answerable(queries, qrels)
    subset = [q for q in pool if qtype == "all" or q.type == qtype][:limit]
    if not subset:
        raise SystemExit(f"クエリ型 {qtype} のクエリが見つかりません")

    dense = dense_index(chunks)
    t0 = time.perf_counter()
    CrossEncoderReranker.get()
    print(f"リランカのロード: {time.perf_counter() - t0:.1f}s")
    print(f"対象: {qtype} {len(subset)}件 / 候補数 {', '.join(str(c) for c in CANDIDATES)}\n")

    print(f"{'条件':<24}{'Recall@10':>9}{'nDCG@10':>9}{'MRR':>8}{'P@10':>8}"
          f"{'合計(s)':>9}{'1クエリ(ms)':>12}")
    print("-" * 82)

    t0 = time.perf_counter()
    rep = evaluate(dense, subset, qrels, k=K, label="dense のみ")
    print(row("dense のみ", rep, time.perf_counter() - t0, len(subset)))

    for c in CANDIDATES:
        rr = RerankRetriever(dense, candidates=c)
        t0 = time.perf_counter()
        rep = evaluate(rr, subset, qrels, k=K, label=f"rerank(候補{c})")
        print(row(f"dense -> rerank(候補{c})", rep, time.perf_counter() - t0, len(subset)))

    print("\n候補数を増やすと到達できる上限は上がるが、1クエリの時間も比例して増える。")
    print("この2列を同じ表で見ないまま候補数を決めてはいけない。")


if __name__ == "__main__":
    main()
