#!/usr/bin/env python3
"""問題9：見出し分割の改良版（極小節の併合）を min_chars を振って測る。"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chunk_lab import chunk_heading_merged  # noqa: E402

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

docs, queries, qrels = load_docs(), load_queries(), load_qrels()


def measure(label: str, chunks) -> None:
    lengths = [len(c.text) for c in chunks]
    report = evaluate(LexicalIndex().build(chunks), queries, qrels, k=10, label=label)
    print(f"{label:<26} n={len(chunks):>5} 平均={statistics.mean(lengths):>5.0f} "
          f"Recall@10={report.macro['recall']:.3f} MRR={report.macro['mrr']:.3f}")


measure("heading(600) 素", chunk_all(docs, "heading", max_chars=600))
for min_chars in (150, 200, 300):
    measure(f"heading_merged(min={min_chars})",
            [c for d in docs for c in chunk_heading_merged(d, 600, min_chars)])
