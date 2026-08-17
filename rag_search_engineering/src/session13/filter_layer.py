#!/usr/bin/env python3
"""権限フィルタを検索層に置く（第3節）。

  (a) フィルタ無し      : 混入する
  (b) 事後フィルタ      : 混入しないが取りこぼす
  (c) 事前フィルタ      : 混入せず、取りこぼしも最小（本書の推奨）
  (d) 空の辞書 {}       : フィルタ無しと同じ（fail-open の罠）
  (e) 拒否リスト        : 未知の値に対して開いてしまう

  docker compose exec app python src/session13/filter_layer.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import (  # noqa: E402
    AccessAwareRetriever,
    PostFilterRetriever,
    Principal,
    leaked_hits,
    lexical_index,
    probe_queries,
    visibility_filter,
)

K = 10
member = Principal(user_id="u-1001", role="member", dept="営業部")
boss = Principal(user_id="u-2001", role="manager", dept="営業部")

index = lexical_index()
probe = probe_queries()[0]
print(f"クエリ: 「{probe.text}」（制限文書を狙って引くプローブ）\n")

pre = AccessAwareRetriever(index, member)
post = PostFilterRetriever(index, member)

rows = [
    ("(a) フィルタ無し", index.search(probe.text, k=K)),
    ("(b) 事後フィルタ", post.search(probe.text, k=K)),
    ("(c) 事前フィルタ", pre.search(probe.text, k=K)),
    ("(d) filters={} ", index.search(probe.text, k=K, filters={})),
]
print("=== 1. 4通りの掛け方 ===")
print(f"  {'条件':<18} {'件数':>4} {'混入':>4}  上位3件の visibility")
for label, hits in rows:
    bad = leaked_hits(hits, member)
    vis = [str(h.meta.get("visibility")) for h in hits[:3]]
    print(f"  {label:<18} {len(hits):>4} {len(bad):>4}  {vis}")

same = [h.chunk_id for h in rows[0][1]] == [h.chunk_id for h in rows[3][1]]
print(f"\n  (a) と (d) の結果は同一か: {same}  ← 空の辞書は「フィルタ無し」と同義")

print("\n=== 2. 権限が上のロールでは何が見えるか ===")
for p in (member, boss):
    hits = AccessAwareRetriever(index, p).search(probe.text, k=K)
    n_restricted = sum(1 for h in hits if h.meta.get("visibility") != "all")
    print(f"  role={p.role:<8} filters={visibility_filter(p)}  "
          f"件数={len(hits):>2} うち制限文書={n_restricted}")

print(
    "\n=== 3. 判定 ===\n"
    "  混入0だけを見るなら (b) でも達成できます。しかし (b) は上位k件から捨てるので、\n"
    "  捨てたぶんだけ結果が痩せます（セッション7の実測：事前4件に対し事後0件）。\n"
    "  権限フィルタは「安全のため」ではなく「安全と件数を両立するため」に前へ置きます。"
)
