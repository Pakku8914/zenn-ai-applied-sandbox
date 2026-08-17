#!/usr/bin/env python3
"""コレクションの設定を読む（セッション7・第3節）。

「HNSW が作られているかどうか」はコレクションの設定と indexed_vectors_count でしか
分からない。検索結果を眺めても絶対に分からないので、最初にここを見る癖をつける。

  docker compose exec app python src/session07/collection_info.py
  docker compose exec app python src/session07/collection_info.py minato_docs_heading
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.dense import DenseIndex  # noqa: E402

COLLECTION = sys.argv[1] if len(sys.argv) > 1 else "minato_docs_fixed"

client = DenseIndex("dummy").client  # コレクションには触らない。クライアントだけ借りる
if not client.collection_exists(COLLECTION):
    raise SystemExit(
        f"{COLLECTION} がありません。先に `python src/session06/verify.py` を実行してください。"
    )

info = client.get_collection(COLLECTION)

vectors_cfg = info.config.params.vectors
if not hasattr(vectors_cfg, "size"):  # 名前付きベクトルのときは辞書で返る
    vectors_cfg = next(iter(vectors_cfg.values()))
distance = getattr(vectors_cfg.distance, "value", vectors_cfg.distance)

hnsw = info.config.hnsw_config
opt = info.config.optimizer_config
schema = info.payload_schema or {}

print(f"コレクション: {COLLECTION}")
print(f"  点数                  : {info.points_count or 0}")
print(f"  インデックス済み      : {info.indexed_vectors_count or 0}")
print(f"  ベクトル              : {vectors_cfg.size}次元 / {distance}")
print(
    f"  HNSW                  : m={hnsw.m} / ef_construct={hnsw.ef_construct} / "
    f"full_scan_threshold={hnsw.full_scan_threshold} (KB)"
)
print(f"  最適化                : indexing_threshold={opt.indexing_threshold} (KB)")
if schema:
    print(
        "  ペイロードインデックス: "
        + " / ".join(
            f"{k}={getattr(v.data_type, 'value', v.data_type)}" for k, v in sorted(schema.items())
        )
    )
else:
    print("  ペイロードインデックス: （なし）")
