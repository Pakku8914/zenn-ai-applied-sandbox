#!/usr/bin/env python3
"""2 つの条件を同じ物差しで比べる（セッション2 練習問題7）。

条件は「チャンク方式」だけを変え、検索方式（BM25）・クエリ集合・判定データ・k は固定する。
1 回に 1 つしか変えないのが比較実験の基本。

    docker compose exec app python src/session02/compare_conditions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

K = 10
CONDITIONS = {
    "fixed": dict(size=400, overlap=80),
    "heading": dict(max_chars=600),
}
ROOT = Path(__file__).resolve().parents[2]

docs, queries, qrels = load_docs(), load_queries(), load_qrels()
reports = {}

for method, params in CONDITIONS.items():
    chunks = chunk_all(docs, method, **params)
    index = LexicalIndex().build(chunks)
    rep = evaluate(index, queries, qrels, k=K, label=f"bm25 / {method}")
    rep.macro["n_chunks"] = float(len(chunks))
    reports[method] = rep
    print(rep.summary())

for method, rep in reports.items():
    out = ROOT / "reports" / f"session02_bm25_{method}.json"
    rep.to_json(out)
    print(f"-> reports/{out.name}")

print("\n--- クエリ型別 Recall@10 ---")
types = sorted(reports["fixed"].by_type)
print(f"{'type':<16}{'fixed':>7}{'heading':>9}")
for t in types:
    a = reports["fixed"].by_type[t]["recall"]
    b = reports["heading"].by_type[t]["recall"]
    print(f"{t:<16}{a:>7.3f}{b:>9.3f}")
