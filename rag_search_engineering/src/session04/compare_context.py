#!/usr/bin/env python3
"""問題8：同じ予算で「畳み込んだ子」と「親」のどちらを渡すかを比べる。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chunk_lab import build_context  # noqa: E402

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

BUDGET = 1200

docs, queries, qrels = load_docs(), load_queries(), load_qrels()
targets = [q for q in queries if q.type in ("natural", "keyword", "multi_condition")][:5]

conditions = {
    "A: fixed + 畳み込み": (
        LexicalIndex().build(chunk_all(docs, "fixed", size=400, overlap=80)), False),
    "B: parent_window + 親": (
        LexicalIndex().build(chunk_all(docs, "parent_window", child=200, window=600)), True),
}

for label, (index, use_parent) in conditions.items():
    print(f"\n=== {label} ===")
    for query in targets:
        relevant = {d for d, g in qrels[query.query_id].items() if g >= 1}
        passages = build_context(index.search(query.text, k=10), budget=BUDGET,
                                 use_parent=use_parent, max_overlap=80)
        hit_count = sum(1 for p in passages if p.doc_id in relevant)
        chars = sum(len(p.text) for p in passages)
        print(f"{query.query_id} 文書数={len(passages)} 文字数={chars} 適合={hit_count}")
