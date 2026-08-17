#!/usr/bin/env python3
"""孤児チャンクの事故を再現して、直す。

文書が短くなると、前の版で作ったチャンクの一部が「欲しい集合」から外れる。
upsert しか流していないと、その点は索引に残り続け、廃止した本文が検索できてしまう。

    python src/session16/orphan.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    count,
    doc_chunk_ids,
    drop,
    find_text,
    make_doc,
    recreate,
    sync,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402

COLLECTION = "minato_s16_orphan"
# 改訂で消える一文。索引に残っていれば、この文字列で見つかる
OBSOLETE = "旧規程：申請は紙の様式で総務部の窓口に提出してください。"


def chunks_of(docs) -> list:
    # 孤児をはっきり見せるため、この節だけ 200 文字・重複なしで切る
    return chunk_all(docs, "fixed", size=200, overlap=0)


def main() -> None:
    client = DenseIndex("dummy").client

    old_a = make_doc("DOC-S16A", 1000, updated_at="2026-05-20", tail=OBSOLETE)
    doc_b = make_doc("DOC-S16B", 600, updated_at="2026-05-20")
    new_a = make_doc("DOC-S16A", 400, updated_at="2026-08-16")

    before_chunks = chunks_of([old_a, doc_b])
    after_chunks = chunks_of([new_a, doc_b])

    print("=== 1. 改訂前の版を索引に載せる ===")
    recreate(client, COLLECTION)
    sync(client, COLLECTION, before_chunks, indexed_at="2026-05-20")
    print(f"  DOC-S16A（1000字）-> {len(chunks_of([old_a]))} チャンク  "
          f"DOC-S16B（600字）-> {len(chunks_of([doc_b]))} チャンク")
    print(f"  点数: {count(client, COLLECTION)}")

    print("\n=== 2. DOC-S16A が 400 字に短くなった（節が削られた）===")
    print(f"  新しいチャンク数: {len(chunks_of([new_a]))}"
          f"（{len(chunks_of([old_a]))} -> {len(chunks_of([new_a]))}）")

    print("\n=== 3. Bad: upsert だけを流す（孤児を掃除しない）===")
    bad = sync(client, COLLECTION, after_chunks, indexed_at="2026-08-16", prune=False)
    print(f"  同期: {bad.line()}")
    print(f"  点数: {count(client, COLLECTION)}（減らない）")
    print(f"  DOC-S16A の点: {len(doc_chunk_ids(client, COLLECTION, 'DOC-S16A'))} 件"
          f"  ← 欲しいのは {len(chunks_of([new_a]))} 件")
    print(f"  廃止された一文を含む点: {find_text(client, COLLECTION, OBSOLETE)}")
    print("  ※ 本文の先頭は変わっていないので upsert すら発生しない。")
    print("     「何も起きなかった」ように見えるのに、古い節が索引に残っている。")

    print("\n=== 4. Good: 欲しい状態にそろえる（upsert + 孤児の削除）===")
    good = sync(client, COLLECTION, after_chunks, indexed_at="2026-08-16")
    print(f"  同期: {good.line()}")
    print(f"  点数: {count(client, COLLECTION)}")
    print(f"  DOC-S16A の点: {len(doc_chunk_ids(client, COLLECTION, 'DOC-S16A'))} 件")
    print(f"  廃止された一文を含む点: {find_text(client, COLLECTION, OBSOLETE)}")

    print("\n=== 5. もう一度流す（冪等）===")
    again = sync(client, COLLECTION, after_chunks, indexed_at="2026-08-16")
    print(f"  同期: {again.line()}")
    print(f"  点数: {count(client, COLLECTION)}")

    drop(client, COLLECTION)
    print("\n一時コレクションを削除しました。")


if __name__ == "__main__":
    main()
