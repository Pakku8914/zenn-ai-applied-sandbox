#!/usr/bin/env python3
"""問題4の解答：フィルタに使う項目にペイロードインデックスを作る。

何度実行しても安全なので、取り込みスクリプトの末尾に置いておける。

  docker compose exec app python src/session07/make_payload_index.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.getLogger("transformers").setLevel(logging.ERROR)

from qdrant_client.models import PayloadSchemaType  # noqa: E402

from ragkit.dense import DenseIndex  # noqa: E402

COLLECTION = "minato_docs_fixed"
QUERY = "社内規程の取り扱いについて"
FIELDS = {"visibility": PayloadSchemaType.KEYWORD, "category": PayloadSchemaType.KEYWORD}

idx = DenseIndex(COLLECTION)
if not idx.client.collection_exists(COLLECTION):
    raise SystemExit(
        "minato_docs_fixed がありません。先に `python src/session06/verify.py` を実行してください。"
    )

before = [h.chunk_id for h in idx.search(QUERY, k=10, filters={"visibility": "manager"})]

for field, schema in FIELDS.items():
    idx.client.create_payload_index(COLLECTION, field_name=field, field_schema=schema, wait=True)
    # もう一度作って冪等であることを確かめる（エラーにならない）
    idx.client.create_payload_index(COLLECTION, field_name=field, field_schema=schema, wait=True)

after = [h.chunk_id for h in idx.search(QUERY, k=10, filters={"visibility": "manager"})]
schema = idx.client.get_collection(COLLECTION).payload_schema or {}

print("インデックス:", " / ".join(sorted(schema)))
print("結果は同じ  :", set(before) == set(after))
