#!/usr/bin/env python3
"""問題4：見出しではない行が見出しとして検出されている箇所を洗い出す。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_heading  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402

HEADING = re.compile(r"^#{1,4}\s*(.+)$", re.MULTILINE)
FENCE = re.compile(r"```.*?```", re.DOTALL)

docs = load_docs()
found = 0
for doc in docs:
    # フェンスで囲まれた範囲にある「見出しに見える行」を洗い出す
    suspects = [m.group(0) for block in FENCE.findall(doc.body)
                for m in HEADING.finditer(block)]
    if not suspects:
        continue
    found += 1
    print(f"{doc.doc_id} {doc.title}")
    for line in suspects:
        print(f"  誤検出される行: {line}")
    for chunk in chunk_heading(doc, 600):
        body = chunk.text[len(doc.title):].lstrip("\n")
        if body.startswith("# "):
            print(f"  分断されたチャンク {chunk.chunk_id}: {body[:40]}...")

print(f"\n誤検出を含む文書: {found} 件")
