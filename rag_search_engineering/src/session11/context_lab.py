#!/usr/bin/env python3
"""セッション11：コンテキストの予算・並び順・親子チャンクを観察する。

合成データだけを使う。コーパスに依存しないので、誰が何回実行しても
1文字も変わらない出力になる（章の説明と突き合わせられる）。

  docker compose exec app python src/session11/context_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from answer_lab import (  # noqa: E402
    STRATEGIES,
    MiddleBlindClient,
    context_hits,
    demo_hits,
    pack_context,
    reorder,
)
from ragkit.answer import answer_with_citations, build_context, build_user_prompt  # noqa: E402
from ragkit.chunk import chunk_parent_window  # noqa: E402
from ragkit.models import Doc, Hit  # noqa: E402

QUERY = "テスト"

print("=== 1. コンテキストの予算（100字ブロック×3件・上限300字）===")
three = demo_hits([100, 100, 100])
ctx = build_context(three, max_chars=300)
packed, taken = pack_context(three, budget=300)
print(f"build_context : {ctx.count('[DOC-')}件 / {len(ctx)}字  ← 区切り文字を予算に数えていない")
print(f"pack_context  : {len(taken)}件 / {len(packed)}字  ← 区切り文字ごと上限を守る")

print()
print("=== 2. 先頭が予算を超えたとき（360/50/50字・上限100字）===")
long_first = demo_hits([360, 50, 50])
_, stop_ids = pack_context(long_first, budget=100)
_, skip_ids = pack_context(long_first, budget=100, stop_on_overflow=False)
print(f"打ち切り方式 (stop_on_overflow=True) : {len(stop_ids)}件 {stop_ids}")
print(f"詰め込み方式 (stop_on_overflow=False): {len(skip_ids)}件 {skip_ids}")

print()
print("=== 3. 並び順（100字ブロック×5件・3番目だけが根拠）===")
five = demo_hits([100] * 5)
target = five[2].chunk_id
base = build_user_prompt(QUERY, five, max_chars=2000)
head = base.index(f"[{five[2].chunk_id}]")
tail = len(base) - base.index(f"[{five[4].chunk_id}]")
print(f"プロンプト {len(base)}字 / 読める窓は先頭{head}字＋末尾{tail}字（3・4番目の位置が死角）")
for strategy in STRATEGIES:
    ordered = reorder(five, strategy)
    client = MiddleBlindClient([target], head=head, tail=tail)
    answer = answer_with_citations(client, QUERY, ordered, max_chars=2000)
    line = " ".join(h.chunk_id for h in ordered)
    print(f"{strategy:<9}: {line}  読めた={answer.answerable}")
print("※ MiddleBlindClient は lost in the middle の戯画。実 LLM の実力を測る道具ではない")

print()
print("=== 4. 親子チャンク（子200／親600・上限1000字）===")
demo_doc = Doc(
    doc_id="DOC-9001",
    title="デモ文書",
    body="あ" * 1000,
    category="勤怠",
    updated_at="2026-08-15",
    visibility="all",
    dept="人事",
    source_type="faq",
    theme="demo",
)
pw = chunk_parent_window(demo_doc, child=200, window=600)
pw_hits = [Hit(c.chunk_id, c.doc_id, 1.0, c.text, c.meta) for c in pw[:5]]
n_child = len(context_hits(pw_hits, max_chars=1000))
n_parent = len(context_hits(pw_hits, max_chars=1000, use_parent=True))
print(f"子の1件 {len(pw_hits[0].text)}字 → 親の1件 {len(pw_hits[0].meta['parent_text'])}字")
print(f"子を渡す: {n_child}件 / 親を渡す: {n_parent}件（同じ予算で入る件数が減る）")
