#!/usr/bin/env python3
"""問題6：複数条件クエリの順位を目視するための出力を作る。

適合文書には * を付けて表示する。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare_methods import METHODS, run  # noqa: E402

from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import hits_to_docs  # noqa: E402

docs, queries, qrels = load_docs(), load_queries(), load_qrels()
target = next(q for q in queries if q.type == "multi_condition")
relevant = {d for d, g in qrels[target.query_id].items() if g >= 1}

print(f"{target.query_id} {target.text}（適合文書 {len(relevant)} 件）")
for method in ("parent_window", "heading"):
    _, _, index = run(method, METHODS[method], docs, queries, qrels)
    ranked = hits_to_docs(index.search(target.text, k=10))
    marks = " ".join(f"{d}{'*' if d in relevant else ''}" for d in ranked)
    print(f"{method:>14}: {marks}")
