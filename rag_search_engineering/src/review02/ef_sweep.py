#!/usr/bin/env python3
"""問題4：673チャンクのコレクションで `ef` を振り、何も起きないことを確かめる。

既存の minato_docs_fixed を読むだけで、コレクションは作り直しません。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fusion_lab import EfIndex, ann_recall_sweep  # noqa: E402

from ragkit.corpus import load_qrels, load_queries  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402

COLLECTION = "minato_docs_fixed"
EFS = (4, 8, 16, 32, 64, 128)

# tools/bench_hnsw.py の実測（合成ベクトル・m=8・ef_construct=32・indexing_threshold=1）
SYNTHETIC = {
    20_000: {4: (0.850, 0.6), 8: (0.850, 0.8), 16: (0.888, 0.6), 32: (0.934, 0.6),
             64: (0.944, 0.6), 128: (0.992, 0.8), "総当たり": (1.000, 1.4)},
    50_000: {4: (0.736, 0.6), 8: (0.736, 0.6), 16: (0.782, 0.6), 32: (0.822, 0.6),
             64: (0.886, 0.6), 128: (0.958, 0.7), "総当たり": (1.000, 2.1)},
}


def main() -> None:
    queries = [q for q in load_queries() if q.type != "unanswerable"]
    qrels = load_qrels()
    idx = DenseIndex(COLLECTION)
    if not idx.client.collection_exists(COLLECTION):
        raise SystemExit(
            f"{COLLECTION} がありません。先にセッション6・7の手順でコレクションを作ってください。"
        )

    info = idx.client.get_collection(COLLECTION)
    indexed = int(info.indexed_vectors_count or 0)
    print(f"点数 {info.points_count} / HNSW に載っているベクトル数 {indexed}")
    print("  → 既定の indexing_threshold（20,000）に届かないので、"
          "Qdrant はグラフを作らず総当たりで探しています")

    print("\n--- ef を振って近似検索のリコールを測る（総当たりを正解とみなす）---")
    sweep = ann_recall_sweep(idx, queries, k=10, efs=EFS)
    for ef, recall in sweep.items():
        print(f"  ef={ef:<5} 近似検索のリコール={recall:.3f}")

    print("\n--- 検索の Recall@10（判定データで測る指標）---")
    for ef in (4, 128):
        rep = evaluate(EfIndex(idx, ef), queries, qrels, k=10, label=f"dense / fixed (ef={ef})")
        print("  " + rep.summary())

    print("\n--- 合成ベクトルでの実測（tools/bench_hnsw.py）---")
    for n, rows in SYNTHETIC.items():
        print(f"  {n:,} 件")
        for ef, (recall, ms) in rows.items():
            label = f"ef={ef}" if isinstance(ef, int) else ef
            print(f"    {label:<10} リコール={recall:.3f}  中央値={ms} ms")


if __name__ == "__main__":
    main()
