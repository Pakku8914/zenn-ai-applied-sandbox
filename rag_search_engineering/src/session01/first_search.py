#!/usr/bin/env python3
"""環境構築の最終確認：BM25 で1件検索して結果を表示する。

モデルのダウンロードが要らないので、環境が整っているかを最短で確かめられる。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all
from ragkit.corpus import load_docs
from ragkit.lexical import LexicalIndex

QUERY = "有給休暇の申請期限"

docs = load_docs()
chunks = chunk_all(docs, "fixed", size=400, overlap=80)
index = LexicalIndex().build(chunks)

print(f"文書数: {len(docs)} / チャンク数: {len(chunks)}")
print(f"クエリ: {QUERY}\n")
for rank, hit in enumerate(index.search(QUERY, k=3), start=1):
    print(f"[{rank}] score={hit.score:.3f}  {hit.chunk_id}  {hit.meta['title']}")
    print(f"    {hit.text[:60].replace(chr(10), ' ')}...")
