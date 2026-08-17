#!/usr/bin/env python3
"""事前フィルタと事後フィルタの違いを見る（セッション7・第7節）。

同じクエリを3通りで検索して、「後段の Python で捨てる」やり方が
何を取りこぼすのかを数える。

  docker compose exec app python src/session07/filter_search.py
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.getLogger("transformers").setLevel(logging.ERROR)

from qdrant_client.models import FieldCondition, Filter, MatchValue  # noqa: E402

from ragkit.corpus import load_docs  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402

COLLECTION = "minato_docs_fixed"
QUERY = "社内規程の取り扱いについて"
TARGET = "manager"
K = 20

idx = DenseIndex(COLLECTION)
if not idx.client.collection_exists(COLLECTION):
    raise SystemExit(
        "minato_docs_fixed がありません。先に `python src/session06/verify.py` を実行してください。"
    )

manager_filter = Filter(must=[FieldCondition(key="visibility", match=MatchValue(value=TARGET))])
n_all = idx.client.count(COLLECTION, exact=True).count
n_target = idx.client.count(COLLECTION, count_filter=manager_filter, exact=True).count
dist = Counter(d.visibility for d in load_docs())

print("=== 1. 母集団 ===")
print("  文書の visibility 分布 : " + " / ".join(f"{k}={v}" for k, v in sorted(dist.items())))
print(f"  コレクションの点数     : {n_all}")
print(f"  visibility={TARGET} の点  : {n_target}")

print("\n=== 2. 同じクエリを3通りで検索する ===")
plain = idx.search(QUERY, k=K)
pre = idx.search(QUERY, k=K, filters={"visibility": TARGET})
post = [h for h in plain if h.meta.get("visibility") == TARGET]
wide = [h for h in idx.search(QUERY, k=200) if h.meta.get("visibility") == TARGET]
print(f"  (a) フィルタなし k={K}                        : {len(plain)} 件")
print(f"  (b) 事前フィルタ visibility={TARGET} k={K}       : {len(pre)} 件")
print(f"  (c) 事後フィルタ（(a) から {TARGET} だけ残す）  : {len(post)} 件")
print(f"  (d) 事後フィルタで k を 200 まで広げる        : {len(wide)} 件")

print("\n=== 3. 判定 ===")
checks = [
    (f"事前フィルタの結果はすべて visibility={TARGET}",
     len(pre) > 0 and all(h.meta.get("visibility") == TARGET for h in pre)),
    (f"k={K} を要求しても母集団の件数しか返らない（候補が枯れている）",
     len(pre) == min(K, n_target) and n_target < K),
    ("事後フィルタ（Python で捨てる）は事前フィルタより取りこぼす", len(post) < len(pre)),
]
for label, ok in checks:
    print(f"  [{'OK' if ok else 'NG'}] {label}")

print(
    "\n事後フィルタは k を広げれば近づきますが、そのぶん要らない候補を計算しています。\n"
    "条件は検索の前に Qdrant へ渡すのが原則です。"
)
