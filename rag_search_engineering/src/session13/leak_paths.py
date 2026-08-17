#!/usr/bin/env python3
"""漏洩経路の棚卸し：1件の制限文書が、どこまで運ばれてしまうかを追う（第1節・第2節）。

「生成側に『答えないで』と書けば守れる」という設計が、なぜ守れないのかを
実物で確かめる。モデルが100%指示に従っても、制限文書の本文は
検索結果・コンテキスト・プロンプト・ログ・キャッシュへ既に流れている。

  docker compose exec app python src/session13/leak_paths.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import Principal, lexical_index, leaked_hits, probe_queries, restricted_docs  # noqa: E402

from ragkit.answer import SYSTEM_PROMPT, build_user_prompt, parse_answer  # noqa: E402
from ragkit.llm import StubClient, cache_key  # noqa: E402

K = 10
member = Principal(user_id="u-1001", role="member", dept="営業部")

docs = restricted_docs()
probes = probe_queries(docs)
index = lexical_index()

print("=== 1. 制限文書（visibility != all）===")
for d in docs:
    print(f"  {d.doc_id}  {d.visibility:<8} {d.title}")

secret = "人事評価の参考情報"  # 制限文書だけに出てくる語

# 混入が起きるプローブを選ぶ（漏洩を再現するのが目的なので、起きるものを使う）
probe = next((p for p in probes if leaked_hits(index.search(p.text, k=K), member)), probes[0])
print(f"\n狙って引くクエリ（プローブ）: 「{probe.text}」")

# --- 経路1: 検索結果そのもの --------------------------------------------------
hits = index.search(probe.text, k=K)
bad = leaked_hits(hits, member)
print("\n=== 2. 経路1：検索結果 ===")
for i, h in enumerate(hits[:5], start=1):
    mark = "★漏洩" if h.meta.get("visibility") != "all" else "     "
    print(f"  {i:>2}. {mark} {h.chunk_id}  visibility={h.meta.get('visibility')}  "
          f"{h.meta.get('title', '')[:32]}")
print(f"  一般社員の権限で見てはいけないヒット: {len(bad)} 件")

if not bad:
    print("  （このクエリでは混入しませんでした。別のプローブで試してください）")

# --- 経路2〜4: コンテキスト・プロンプト・引用 ---------------------------------
user_prompt = build_user_prompt(probe.text, hits, max_chars=2000)
rank = next((i for i, h in enumerate(hits, start=1) if h in bad), None)
print("\n=== 3. 経路2〜4：コンテキスト / プロンプト / 引用 ===")
print(f"  制限文書の順位                    : {rank} 位（上位ほどコンテキストに入りやすい）")
print(f"  プロンプト長                      : {len(user_prompt)} 文字")
print(f"  プロンプトに制限文書の本文が入ったか: {secret in user_prompt}")
print(f"  引用候補に出せる chunk_id          : "
      f"{[h.chunk_id for h in hits if h.meta.get('visibility') != 'all'][:3]}")

# 指示に完全に従うモデルを模したスタブ（本書は課金なしで回す）
obedient = StubClient(
    default='{"answerable": false, "answer": "権限がないため回答できません。", "citations": []}'
)
answer = parse_answer(obedient.complete(SYSTEM_PROMPT, user_prompt).text)
print(f"  モデルの応答（完全に指示に従った場合）: {answer.text}")
print(f"  回答本文に秘密が出たか              : {secret in answer.text}")

# --- 経路5〜6: ログとキャッシュ -----------------------------------------------
access_log = {
    "user_id": member.user_id,
    "query": probe.text,
    "top_chunk_ids": [h.chunk_id for h in hits[:3]],
    "top_titles": [h.meta.get("title", "") for h in hits[:3]],
    "prompt_cache_key": cache_key(SYSTEM_PROMPT, user_prompt),
}
print("\n=== 4. 経路5〜6：ログ / キャッシュ ===")
print(f"  ログに残る題名 : {access_log['top_titles'][:2]}")
print(f"  ログに制限文書の題名が残ったか: "
      f"{any('管理職限定' in t for t in access_log['top_titles'])}")
print(f"  キャッシュキー : {access_log['prompt_cache_key']}（本文はキャッシュの値の側に丸ごと残る）")

print(
    "\n=== 5. 判定 ===\n"
    "  モデルは指示どおり黙りました。にもかかわらず、制限文書の本文は\n"
    "  検索結果・コンテキスト・プロンプト（＝外部APIへの送信内容）・ログ・キャッシュに\n"
    "  すでに載っています。生成の出力を止めることは、漏洩を止めることではありません。\n"
    "  止めるべき場所は、候補を作る検索層です。"
)
