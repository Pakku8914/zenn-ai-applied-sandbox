#!/usr/bin/env python3
"""チャンク方式ごとに密ベクトル索引を作り、時間と精度を同時に測る（セッション6・問題9）。

索引作成時間はチャンク数ではなく総トークン数（1件あたりの長さ）で決まる。
件数が3倍の heading の方が fixed より速い、という結果になる。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.dense import DenseIndex, Embedder  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402

CONFIGS = {"fixed": dict(size=400, overlap=80), "heading": dict(max_chars=600)}


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    Embedder.get()  # ロード（6.7 秒）を計測から外す

    for method, params in CONFIGS.items():
        chunks = chunk_all(docs, method, **params)
        t0 = time.perf_counter()
        idx = DenseIndex(f"minato_docs_{method}").build(chunks)  # 時間を測るので毎回作り直す
        build_sec = time.perf_counter() - t0

        rep = evaluate(idx, queries, qrels, k=10, label=f"dense / {method}")
        avg_len = sum(len(c.text) for c in chunks) / len(chunks)
        print(rep.summary())
        print(f"  チャンク数 {len(chunks):>5} / 平均長 {avg_len:5.1f} 字"
              f" / 索引作成 {build_sec:5.1f} 秒"
              f" / 1件あたり {build_sec / len(chunks) * 1000:5.1f} ms")
        print("  型別 " + " ".join(
            f"{t}={v['recall']:.3f}" for t, v in sorted(rep.by_type.items())))


if __name__ == "__main__":
    main()
