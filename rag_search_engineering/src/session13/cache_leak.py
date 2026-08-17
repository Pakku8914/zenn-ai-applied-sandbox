#!/usr/bin/env python3
"""キャッシュとフィルタの相互作用（第7節）。

フィルタを正しく実装しても、キャッシュの鍵に権限が入っていないと漏洩が復活する。
さらに、権限を後から厳しくしたとき（all -> manager）、索引を直しただけでは
キャッシュに残った古い結果が返り続ける。

  docker compose exec app python src/session13/cache_leak.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import (  # noqa: E402
    AccessAwareRetriever,
    Principal,
    SearchCache,
    leaked_hits,
    lexical_index,
    probe_queries,
)

K = 10
MEMBER = Principal(user_id="u-1001", role="member", dept="営業部")
BOSS = Principal(user_id="u-2001", role="manager", dept="営業部")


def set_visibility(index, doc_id: str, visibility: str) -> dict[str, str]:
    """索引の中のメタデータだけを書き換える（Qdrant の set_payload に相当）。

    戻り値は元の値。テストの後で必ず戻せるようにしておく。
    """
    before: dict[str, str] = {}
    for chunk_id, chunk in list(index.chunks.items()):
        if chunk.doc_id == doc_id:
            before[chunk_id] = chunk.meta.get("visibility", "")
            index.chunks[chunk_id] = replace(
                chunk, meta={**chunk.meta, "visibility": visibility}
            )
    return before


def restore_visibility(index, before: dict[str, str]) -> None:
    for chunk_id, visibility in before.items():
        chunk = index.chunks[chunk_id]
        index.chunks[chunk_id] = replace(chunk, meta={**chunk.meta, "visibility": visibility})


index = lexical_index()
probes = probe_queries()
probe = next(
    (p for p in probes if leaked_hits(index.search(p.text, k=K), MEMBER)), probes[0]
)
print(f"共有されるクエリ: 「{probe.text}」\n")

# --- 1. 鍵の作り方を3通り比べる ------------------------------------------------
print("=== 1. 同じクエリを、上司 -> 一般社員 の順に投げる ===")
print(f"  {'key_mode':<12} {'2人目はヒットしたか':<20} {'一般社員への混入':>16}")
for mode in ("query_only", "principal", "user"):
    cache = SearchCache(mode)
    cache.get_or_search(AccessAwareRetriever(index, BOSS), BOSS, probe.text, k=K)
    hits = cache.get_or_search(AccessAwareRetriever(index, MEMBER), MEMBER, probe.text, k=K)
    bad = leaked_hits(hits, MEMBER)
    print(f"  {mode:<12} {'ヒット（再利用）' if cache.hit_count else 'ミス（引き直し）':<20} "
          f"{len(bad):>10} 件")

print(
    "\n  query_only は鍵に権限が入っていないので、上司の結果がそのまま配られます。\n"
    "  principal は「見える範囲が同じ人」で共有するので、安全でヒット率も保てます。\n"
    "  user は最も安全ですが、利用者が増えるほどヒット率が落ちます。"
)

# --- 2. 権限を厳しくしたとき（all -> manager）----------------------------------
print("\n=== 2. 公開範囲を後から厳しくする（all -> manager）===")
victim = index.search(probe.text, k=K)
public = [h for h in victim if h.meta.get("visibility") == "all"]
doc_id = public[0].doc_id if public else victim[0].doc_id

cache = SearchCache("principal")
before_hits = cache.get_or_search(AccessAwareRetriever(index, MEMBER), MEMBER, probe.text, k=K)
print(f"  秘匿化する文書 : {doc_id}")
print(f"  変更前：一般社員の結果に含まれるか: {any(h.doc_id == doc_id for h in before_hits)}")

original = set_visibility(index, doc_id, "manager")
try:
    cached = cache.get_or_search(AccessAwareRetriever(index, MEMBER), MEMBER, probe.text, k=K)
    print(f"  索引だけ更新：まだ含まれるか      : {any(h.doc_id == doc_id for h in cached)}"
          "  ← キャッシュが古い結果を返している")

    dropped = cache.invalidate_doc(doc_id)
    fresh = cache.get_or_search(AccessAwareRetriever(index, MEMBER), MEMBER, probe.text, k=K)
    print(f"  キャッシュ無効化（{dropped} 件破棄）後 : "
          f"{any(h.doc_id == doc_id for h in fresh)}")
finally:
    restore_visibility(index, original)

print(
    "\n=== 3. 判定 ===\n"
    "  権限の変更は「索引の更新」と「キャッシュの無効化」の2つで初めて完了します。\n"
    "  厳しくする変更（秘匿化・削除）は、無効化が終わるまで完了と呼べません。"
)
