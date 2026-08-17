#!/usr/bin/env python3
"""増分更新：追加・更新・削除の3種を検出して、冪等に索引へ流し込む。

    python src/session16/incremental.py

埋め込みモデルは使わない（ベクトルは common.vector_for が本文から決定的に作る）。
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    count,
    diff_by_updated_at,
    diff_docs,
    doc_chunk_ids,
    doc_state,
    drop,
    index_state,
    recreate,
    sync,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402

COLLECTION = "minato_s16_incremental"
LAST_RUN = "2026-08-15"  # 前回バッチを回した日
TODAY = "2026-08-16"  # 今回のバッチ
REVISION = "\n2026-08-16 改訂：申請の締切を1営業日前倒しします。"


def build_versions() -> tuple[list, list, list, dict]:
    """前回の版・今回の版・（改訂日を直し忘れた）今回の版を作る。"""
    docs = load_docs()
    previous = docs[:20]
    base = previous[3]  # 更新する文書
    removed = previous[7]  # 削除する文書
    incoming = replace(docs[20], updated_at=TODAY)  # 追加される文書

    changed = replace(base, body=base.body + REVISION, updated_at=TODAY)
    # 現場でよくある事故：本文を直したのに改訂日を直し忘れる
    changed_stale = replace(base, body=base.body + REVISION)

    keep = [d for d in previous if d.doc_id != removed.doc_id]
    current = [changed if d.doc_id == base.doc_id else d for d in keep] + [incoming]
    stale = [changed_stale if d.doc_id == base.doc_id else d for d in keep] + [incoming]
    return previous, current, stale, {
        "changed": base.doc_id,
        "removed": removed.doc_id,
        "added": incoming.doc_id,
    }


def chunks_of(docs) -> list:
    return chunk_all(docs, "fixed", size=400, overlap=80)


def main() -> None:
    client = DenseIndex("dummy").client
    previous, current, stale, ids = build_versions()

    print("=== 1. 前回の版を索引に載せる（初回構築）===")
    recreate(client, COLLECTION)
    prev_chunks = chunks_of(previous)
    stats = sync(client, COLLECTION, prev_chunks, indexed_at=LAST_RUN)
    print(f"  文書 {len(previous)} 件 / チャンク {len(prev_chunks)} 個")
    print(f"  同期: {stats.line()}")
    print(f"  点数: {count(client, COLLECTION)}")

    print("\n=== 2. 何も変えずにもう一度流す（冪等）===")
    again = sync(client, COLLECTION, prev_chunks, indexed_at=LAST_RUN)
    print(f"  同期: {again.line()}")
    print(f"  点数: {count(client, COLLECTION)}（変わらない）")

    print("\n=== 3. 今回の版との差分（追加1・更新1・削除1）===")
    state = doc_state(previous)
    diff = diff_docs(state, current)
    by_date = diff_by_updated_at(current, LAST_RUN)
    by_date_stale = diff_by_updated_at(stale, LAST_RUN)
    print("  検出方法                                    追加  更新  削除")
    print(f"  更新日（updated_at > {LAST_RUN}）              "
          f"{sum(1 for d in by_date if d in diff.added):>2}    "
          f"{sum(1 for d in by_date if d in diff.changed):>2}     -")
    print("  更新日（改訂日の直し忘れが1件ある場合）        "
          f"{sum(1 for d in by_date_stale if d in diff.added):>2}    "
          f"{sum(1 for d in by_date_stale if d in diff.changed):>2}     -")
    c = diff.counts()
    print(f"  内容ハッシュ（前回の一覧と突き合わせ）        "
          f"{c['added']:>2}    {c['changed']:>2}     {c['removed']}")
    print(f"  変更なし: {c['unchanged']} 件")
    print(f"  更新: {ids['changed']} / 削除: {ids['removed']} / 追加: {ids['added']}")

    print("\n=== 4. 差分を流し込む ===")
    before = index_state(client, COLLECTION)
    cur_chunks = chunks_of(current)
    stats = sync(client, COLLECTION, cur_chunks, indexed_at=TODAY)
    after = index_state(client, COLLECTION)
    print(f"  同期: {stats.line()}")
    print(f"  点数: {count(client, COLLECTION)}")
    touched = [
        cid for cid, info in after.items()
        if cid in before and before[cid]["content_hash"] != info["content_hash"]
    ]
    print(f"  指紋が入れ替わった点: {len(touched)} 件 {sorted(touched)}")
    print(f"  削除した文書の点が残っているか: "
          f"{bool(doc_chunk_ids(client, COLLECTION, ids['removed']))}")
    print(f"  追加した文書の点: {len(doc_chunk_ids(client, COLLECTION, ids['added']))} 件")

    print("\n=== 5. もう一度流す（冪等）===")
    final = sync(client, COLLECTION, cur_chunks, indexed_at=TODAY)
    print(f"  同期: {final.line()}")
    print(f"  点数: {count(client, COLLECTION)}")

    drop(client, COLLECTION)
    print("\n一時コレクションを削除しました。")


if __name__ == "__main__":
    main()
