#!/usr/bin/env python3
"""前処理の1行がチャンク方式を別物にすることを、0/1で示す。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from review_lab import strip_docs  # noqa: E402

from ragkit.chunk import chunk_heading, chunk_sentence  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402

HEADING = re.compile(r"^#{1,4}\s*(.+)$", re.MULTILINE)

docs = load_docs()
stripped = strip_docs(docs)

# ① コーパス自体は変わっていない（件数と文字数で確認する）
print(f"文書数 {len(docs)} → {len(stripped)}")
print(f"総文字数 {sum(len(d.full_text) for d in docs)} → "
      f"{sum(len(d.full_text) for d in stripped)}")

# ② 見出し行の有無だけが変わっている
print(f"見出しを持つ文書 {sum(1 for d in docs if HEADING.search(d.body))} → "
      f"{sum(1 for d in stripped if HEADING.search(d.body))}")

# ③ チャンク数が激減する
before = [c for d in docs for c in chunk_heading(d, 600)]
after = [c for d in stripped for c in chunk_heading(d, 600)]
print(f"heading(600) のチャンク数 {len(before)} → {len(after)}")

# ④ 決定的な証拠：前処理後の heading は sentence と1文字も違わない
sent = [c for d in stripped for c in chunk_sentence(d, 600)]
same = [(c.chunk_id, c.text) for c in after] == [(c.chunk_id, c.text) for c in sent]
print(f"前処理後の heading == sentence : {same}")
