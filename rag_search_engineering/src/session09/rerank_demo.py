#!/usr/bin/env python3
"""1段目の順位とリランク後の順位を並べて、何が起きたのかを1クエリ単位で見る。

実行:  docker compose exec app python src/session09/rerank_demo.py
      docker compose exec app python src/session09/rerank_demo.py multi_condition 20
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ceiling_recall, dense_index, first_of_type, load_all, mark, rank_of  # noqa: E402

from ragkit.eval import mrr, ndcg_at_k, recall_at_k  # noqa: E402
from ragkit.rerank import CrossEncoderReranker  # noqa: E402

K = 10


def show(title: str, hits, qr, before_rank: dict[str, int] | None = None) -> None:
    print(f"  {title}")
    header = f"    {'順位':<4}{'適合':<4}{'chunk_id':<18}{'スコア':>9}"
    print(header + ("   1段目順位" if before_rank else ""))
    for i, h in enumerate(hits[:K], start=1):
        row = f"    {i:<6}{mark(qr, h.doc_id):<4}{h.chunk_id:<18}{h.score:>9.4f}"
        if before_rank:
            row += f"   {before_rank.get(h.chunk_id, '-'):>5}"
        print(row)
    print(f"    Recall@{K}={recall_at_k(hits, qr, K):.3f} "
          f"nDCG@{K}={ndcg_at_k(hits, qr, K):.3f} MRR={mrr(hits, qr):.3f}")


def main() -> None:
    qtype = sys.argv[1] if len(sys.argv) > 1 else "multi_condition"
    candidates = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    _docs, queries, qrels, chunks = load_all()
    dense = dense_index(chunks)
    CrossEncoderReranker.get()  # ロードの時間を計測に混ぜない

    for query in first_of_type(queries, qrels, qtype, n=2):
        qr = qrels[query.query_id]
        print(f"\n=== {query.query_id} [{query.type}] {query.text}")

        base = dense.search(query.text, k=K)
        pool = dense.search(query.text, k=candidates)
        t0 = time.perf_counter()
        after = CrossEncoderReranker.rerank(query.text, pool, top_k=K)
        elapsed = (time.perf_counter() - t0) * 1000

        show(f"1段目（dense・上位{K}件）", base, qr)
        print()
        show(f"リランク後（候補{candidates}件 -> 上位{K}件・{elapsed:.0f}ms）",
             after, qr, before_rank=rank_of(pool))
        ceiling = ceiling_recall(pool, qr, K)
        print(f"    到達上限（候補{candidates}件から選び直せる Recall@{K} の上限）= {ceiling:.3f}")
        moved = sum(1 for i, h in enumerate(after[:K], start=1) if rank_of(pool).get(h.chunk_id) != i)
        print(f"    上位{K}件のうち順位が動いたチャンク: {moved} 件")


if __name__ == "__main__":
    main()
