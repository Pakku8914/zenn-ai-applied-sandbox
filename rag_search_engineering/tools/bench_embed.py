#!/usr/bin/env python3
"""埋め込みの CPU 実測（索引作成時間とクエリのエンコード時間）。

セッション6・7で「10万文書ならどれくらいかかるか」を見積もる根拠にする。
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.dense import Embedder  # noqa: E402


def main() -> None:
    docs = load_docs()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)
    texts = [c.text for c in chunks]

    t0 = time.perf_counter()
    Embedder.get()
    load_sec = time.perf_counter() - t0
    print(f"モデルのロード          : {load_sec:.1f}s")

    for batch_size in (8, 16, 32):
        sample = texts[:200]
        t0 = time.perf_counter()
        Embedder.encode_passages(sample, batch_size=batch_size)
        dt = time.perf_counter() - t0
        print(f"passage 200件 (batch={batch_size:>2}) : {dt:.2f}s "
              f"({dt / len(sample) * 1000:.1f} ms/件, {len(sample) / dt:.1f} 件/秒)")

    t0 = time.perf_counter()
    vecs = Embedder.encode_passages(texts, batch_size=16)
    dt = time.perf_counter() - t0
    print(f"passage 全{len(texts)}件         : {dt:.2f}s "
          f"({dt / len(texts) * 1000:.1f} ms/件)  次元={vecs.shape[1]}")
    print(f"  -> 10万チャンクの見積もり : {dt / len(texts) * 100_000 / 60:.1f}分")

    lat = []
    for _ in range(20):
        t0 = time.perf_counter()
        Embedder.encode_query("有給休暇の申請期限を教えてください")
        lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    print(f"query 1件のエンコード     : 中央値 {statistics.median(lat):.1f}ms / "
          f"p95 {lat[18]:.1f}ms / 最大 {lat[-1]:.1f}ms")


if __name__ == "__main__":
    main()
