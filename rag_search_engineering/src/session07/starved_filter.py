#!/usr/bin/env python3
"""問題8の解答：候補が枯れる条件を探し、3つの対処を比べる。

  docker compose exec app python src/session07/starved_filter.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.getLogger("transformers").setLevel(logging.ERROR)

from qdrant_client.models import FieldCondition, Filter, MatchValue  # noqa: E402

from ragkit.dense import DenseIndex  # noqa: E402

COLLECTION = "minato_docs_fixed"
QUERY = "社内規程の取り扱いについて"
K = 10
CATEGORIES = ["セキュリティ", "勤怠", "経費", "PC・端末", "アカウント", "オフィス"]

idx = DenseIndex(COLLECTION)
if not idx.client.collection_exists(COLLECTION):
    raise SystemExit(
        "minato_docs_fixed がありません。先に `python src/session06/verify.py` を実行してください。"
    )


def population(**conds) -> int:
    """条件に合う点数を厳密に数える（検索する前に母集団を知る）。"""
    f = Filter(must=[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in conds.items()])
    return idx.client.count(COLLECTION, count_filter=f, exact=True).count


# --- 枯れる条件を探す -------------------------------------------------------
print("visibility=manager × category の母集団")
starved = []
for cat in CATEGORIES:
    n = population(visibility="manager", category=cat)
    print(f"  category={cat} : {n} 点")
    if n < K:
        starved.append((cat, n))

if not starved:
    raise SystemExit("枯れる条件が見つかりませんでした（コーパスを作り直してください）")

cat, n = starved[0]

# --- 対処A: k を母集団に丸める ----------------------------------------------
k_a = min(K, n)
hits_a = (
    idx.search(QUERY, k=k_a, filters={"visibility": "manager", "category": cat}) if k_a else []
)

# --- 対処B: 条件を段階的に緩める（visibility は絶対に外さない）--------------
hits_b = idx.search(QUERY, k=K, filters={"visibility": "manager", "category": cat})
searches_b = 1
if len(hits_b) < K:  # category だけを外して再検索する
    hits_b = idx.search(QUERY, k=K, filters={"visibility": "manager"})
    searches_b = 2

# --- 対処C: そのまま返す ----------------------------------------------------
hits_c = idx.search(QUERY, k=K, filters={"visibility": "manager", "category": cat})

print(f"\n条件: visibility=manager / category={cat}（母集団 {n} 点）")
print(f"  対処A（k を丸める）   : {len(hits_a)} 件 / 検索1回 / 余計なものは混ざらない")
print(f"  対処B（条件を緩める） : {len(hits_b)} 件 / 検索{searches_b}回 / category 外のものが混ざる")
print(f"  対処C（そのまま返す） : {len(hits_c)} 件 / 検索1回 / 余計なものは混ざらない")
