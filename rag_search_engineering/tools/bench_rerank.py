#!/usr/bin/env python3
"""リランクの CPU 実測（候補数ごとのレイテンシと精度）。

セッション9で「レイテンシ予算からリランクの候補数を逆算する」根拠にする。
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.rerank import CrossEncoderReranker, RerankRetriever  # noqa: E402

CANDIDATES = (10, 20, 50, 100)


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)
    base = DenseIndex("minato_docs_fixed")
    if not base.client.collection_exists("minato_docs_fixed"):
        print("コレクションが無いので作成します（数十秒かかります）")
        base.build(chunks)

    t0 = time.perf_counter()
    CrossEncoderReranker.get()
    print(f"リランカのロード : {time.perf_counter() - t0:.1f}s\n")

    query = "有給休暇の申請期限を教えてください"
    hits = base.search(query, k=max(CANDIDATES))
    print(f"{'候補数':>6}{'中央値(ms)':>12}{'最大(ms)':>10}{'1件あたり(ms)':>16}")
    print("-" * 46)
    for k in CANDIDATES:
        lat = []
        for _ in range(3):
            t0 = time.perf_counter()
            CrossEncoderReranker.rerank(query, hits[:k], top_k=10)
            lat.append((time.perf_counter() - t0) * 1000)
        med = statistics.median(lat)
        print(f"{k:>6}{med:>12.0f}{max(lat):>10.0f}{med / k:>16.1f}")

    print("\n=== 候補数と精度（全クエリ）===")
    rep = evaluate(base, queries, qrels, k=10, label="dense のみ")
    print(rep.summary())
    for k in (20, 50):
        rr = RerankRetriever(base, candidates=k)
        rep = evaluate(rr, queries, qrels, k=10, label=f"dense -> rerank(候補{k})")
        print(rep.summary())


if __name__ == "__main__":
    main()
