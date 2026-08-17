#!/usr/bin/env python3
"""検索方式 × チャンク方式の精度マトリクスを出す。

本書で最も参照される実測値の出典。reports/eval_matrix.json に保存する。

  python tools/eval_matrix.py              # 既定（レキシカル4方式 + 密2方式 + ハイブリッド）
  python tools/eval_matrix.py --quick      # レキシカルのみ（モデル不要・数秒）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.hybrid import HybridRetriever  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

K = 10
CHUNK_CONFIGS = {
    "fixed": dict(size=400, overlap=80),
    "sentence": dict(max_chars=400),
    "heading": dict(max_chars=600),
    "parent_window": dict(child=200, window=600),
}
REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="レキシカルのみ実行する")
    args = ap.parse_args()

    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    results = []

    # --- レキシカル（BM25）: 4つのチャンク方式 -----------------------------
    for method, params in CHUNK_CONFIGS.items():
        chunks = chunk_all(docs, method, **params)
        idx = LexicalIndex().build(chunks)
        t0 = time.perf_counter()
        rep = evaluate(idx, queries, qrels, k=K, label=f"bm25 / {method}")
        rep.macro["elapsed_sec"] = round(time.perf_counter() - t0, 2)
        rep.macro["n_chunks"] = len(chunks)
        results.append(rep)
        print(rep.summary())

    if not args.quick:
        from ragkit.dense import DenseIndex

        # --- 密ベクトル検索: fixed と heading -----------------------------
        dense_indexes = {}
        for method in ("fixed", "heading"):
            chunks = chunk_all(docs, method, **CHUNK_CONFIGS[method])
            t0 = time.perf_counter()
            idx = DenseIndex(f"minato_docs_{method}").build(chunks)
            build_sec = time.perf_counter() - t0
            dense_indexes[method] = idx
            rep = evaluate(idx, queries, qrels, k=K, label=f"dense / {method}")
            rep.macro["n_chunks"] = len(chunks)
            rep.macro["index_build_sec"] = round(build_sec, 2)
            results.append(rep)
            print(rep.summary() + f"  [索引作成 {build_sec:.1f}s]")

        # --- ハイブリッド（RRF / min-max）: fixed --------------------------
        chunks = chunk_all(docs, "fixed", **CHUNK_CONFIGS["fixed"])
        lex = LexicalIndex().build(chunks)
        for mode in ("rrf", "minmax"):
            hyb = HybridRetriever([lex, dense_indexes["fixed"]], candidates=50, mode=mode)
            rep = evaluate(hyb, queries, qrels, k=K, label=f"hybrid({mode}) / fixed")
            results.append(rep)
            print(rep.summary())

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "eval_matrix.json"
    out.write_text(
        json.dumps(
            [{"label": r.label, "k": r.k, "macro": r.macro, "by_type": r.by_type} for r in results],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n-> {out.relative_to(out.parent.parent)}")

    print("\n=== クエリ型別 Recall@10 ===")
    types = sorted({t for r in results for t in r.by_type})
    print(f"{'条件':<26}" + "".join(f"{t:>16}" for t in types))
    for r in results:
        print(f"{r.label:<26}" + "".join(
            f"{r.by_type.get(t, {}).get('recall', float('nan')):>16.3f}" for t in types))


if __name__ == "__main__":
    main()
