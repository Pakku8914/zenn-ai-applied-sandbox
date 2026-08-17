#!/usr/bin/env python3
"""並行構築と切り替え：検索を止めずにチャンク方式を入れ替える手順を実行する。

    python src/session16/switch.py

セッション7で仕組み（エイリアスの付け替え）は確認済み。ここでは
「並行構築 → 追いつき → 点検 → 切り替え → 検証 → 切り戻し」という手順として組み立てる。
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    alias_target,
    count,
    drop,
    drop_alias,
    index_state,
    recreate,
    switch_alias,
    sync,
    vector_for,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402

ALIAS = "minato_s16_switch"
V1 = "minato_s16_switch_v1"
V2 = "minato_s16_switch_v2"
PROBE = vector_for("プローブ").tolist()


def method_via_alias(client) -> str:
    """エイリアス経由で1件引いて、どちらの方式の索引を見ているかを返す。"""
    res = client.query_points(ALIAS, query=PROBE, limit=1, with_payload=True)
    return (res.points[0].payload or {}).get("method", "?")


def n_docs(client, collection: str) -> int:
    return len({info["doc_id"] for info in index_state(client, collection).values()})


def main() -> None:
    client = DenseIndex("dummy").client
    docs = load_docs()[:20]

    print("=== 1. 現行（v1・fixed 400/80）を用意し、エイリアスを向ける ===")
    recreate(client, V1)
    v1_chunks = chunk_all(docs, "fixed", size=400, overlap=80)
    sync(client, V1, v1_chunks, indexed_at="2026-08-15")
    switch_alias(client, ALIAS, V1)
    print(f"  {V1}: {count(client, V1)} 点 / 文書 {n_docs(client, V1)} 件")
    print(f"  {ALIAS} -> {alias_target(client, ALIAS)}")
    print(f"  エイリアス経由で見ている方式: {method_via_alias(client)}")

    print("\n=== 2. 新方式（v2・heading 600）を並行構築する。検索は止まらない ===")
    recreate(client, V2)
    v2_chunks = chunk_all(docs, "heading", max_chars=600)
    sync(client, V2, v2_chunks, indexed_at="2026-08-16")
    print(f"  {V2}: {count(client, V2)} 点 / 文書 {n_docs(client, V2)} 件")
    print(f"  エイリアス経由で見ている方式: {method_via_alias(client)}（現行のまま）")

    print("\n=== 3. 並行構築中に届いた更新を、両系統へ流す（追いつき）===")
    updated = replace(docs[2], body=docs[2].body + "\n2026-08-16 改訂：受付時間を変更します。",
                      updated_at="2026-08-16")
    docs_now = [updated if d.doc_id == updated.doc_id else d for d in docs]
    s1 = sync(client, V1, chunk_all(docs_now, "fixed", size=400, overlap=80),
              indexed_at="2026-08-16")
    s2 = sync(client, V2, chunk_all(docs_now, "heading", max_chars=600), indexed_at="2026-08-16")
    print(f"  v1 へ: {s1.line()}")
    print(f"  v2 へ: {s2.line()}")
    print("  ※ 片方だけに流すと、切り替えた瞬間に更新が巻き戻る")

    print("\n=== 4. 引き渡し前の点検 ===")
    checks = [
        ("孤児が残っていない（v2）", not sync(
            client, V2, chunk_all(docs_now, "heading", max_chars=600), dry_run=True).orphans),
        ("文書数が一致する", n_docs(client, V1) == n_docs(client, V2) == len(docs)),
        ("v2 の点数が0でない", count(client, V2) > 0),
    ]
    for label, ok in checks:
        print(f"  {'OK ' if ok else 'NG '} {label}")
    if not all(ok for _, ok in checks):
        print("  点検に落ちたので切り替えません。")
        drop_alias(client, ALIAS)
        drop(client, V1, V2)
        raise SystemExit(1)

    print("\n=== 5. 切り替え（1リクエストで原子的に入れ替わる）===")
    switch_alias(client, ALIAS, V2)
    print(f"  {ALIAS} -> {alias_target(client, ALIAS)}")
    print(f"  エイリアス経由で見ている方式: {method_via_alias(client)}")

    print("\n=== 6. 切り戻し（v1 を消していないので一瞬で戻せる）===")
    switch_alias(client, ALIAS, V1)
    print(f"  {ALIAS} -> {alias_target(client, ALIAS)}")
    print(f"  エイリアス経由で見ている方式: {method_via_alias(client)}")

    print("\n=== 7. 後片付け（保持期間を過ぎてから旧版を消す）===")
    drop_alias(client, ALIAS)
    drop(client, V1, V2)
    print("  エイリアスと一時コレクションを削除しました。")


if __name__ == "__main__":
    main()
