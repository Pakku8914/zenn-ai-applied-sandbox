#!/usr/bin/env python3
"""問題2：自作の固定長分割が ragkit.chunk.chunk_fixed と一致するかを確認する。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chunk_lab import fixed_chunks  # noqa: E402

from ragkit.chunk import chunk_fixed  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402

docs = load_docs()
total = 0
mismatch: list[str] = []
for doc in docs:
    mine = [p.strip() for p in fixed_chunks(doc.full_text, 400, 80) if p.strip()]
    theirs = [c.text for c in chunk_fixed(doc, 400, 80)]
    total += len(mine)
    if mine != theirs:
        mismatch.append(doc.doc_id)

print(f"チャンク数: {total}")
print(f"不一致の文書: {len(mismatch)} 件 {mismatch[:5]}")
