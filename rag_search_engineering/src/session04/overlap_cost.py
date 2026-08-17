#!/usr/bin/env python3
"""問題3：オーバーラップを振って、索引にかかる掛け金（重複率・ポスティング数）を測る。"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

SIZE = 400
OVERLAPS = [0, 40, 80, 160, 200]

docs = load_docs()
base_chars = sum(len(d.full_text) for d in docs)
print(f"元テキスト総文字数={base_chars:,} / size={SIZE}\n")
print(f"{'overlap':>8}{'チャンク数':>12}{'平均長':>8}{'重複率':>8}"
      f"{'語彙数':>10}{'ポスティング数':>16}{'理論上限':>10}")
for overlap in OVERLAPS:
    chunks = chunk_all(docs, "fixed", size=SIZE, overlap=overlap)
    index = LexicalIndex().build(chunks)
    postings = sum(len(v) for v in index.postings.values())
    duplication = sum(len(c.text) for c in chunks) / base_chars
    mean_length = statistics.mean([len(c.text) for c in chunks])
    print(f"{overlap:>8}{len(chunks):>12}{mean_length:>8.0f}"
          f"{duplication:>8.2f}{len(index.postings):>10}{postings:>16}"
          f"{SIZE / (SIZE - overlap):>10.2f}")
