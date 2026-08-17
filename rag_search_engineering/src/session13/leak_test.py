#!/usr/bin/env python3
"""権限別に全クエリを回して混入0を確認する（第4節）。この章の成果物そのもの。

業務クエリ120件（回答不能10件を含む）に、制限文書を狙って引くプローブクエリを足した
集合を、権限ごとに全件回して「見てはいけないチャンクが1件でも返っていないか」を数える。
1件でも混入したら非0終了する（CI に置けるテストにするため）。

  docker compose exec app python src/session13/leak_test.py
  docker compose exec app python src/session13/leak_test.py --dense   # 密ベクトルでも回す
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import (  # noqa: E402
    AccessAwareRetriever,
    PostFilterRetriever,
    Principal,
    SweepResult,
    dense_index,
    leak_test_queries,
    lexical_index,
    sweep,
)

K = 10
MEMBER = Principal(user_id="u-1001", role="member", dept="営業部")
BOSS = Principal(user_id="u-2001", role="manager", dept="営業部")


def run_all(inner, label: str, queries, k: int = K) -> list[SweepResult]:
    """1つの検索器について、4通りの掛け方で混入検査を回す。"""
    results: list[SweepResult] = []

    # (1) 対照群：フィルタを付け忘れた状態を、一般社員の基準で採点する
    results.append(
        sweep(lambda q, kk: inner.search(q, k=kk), MEMBER, queries, k,
              label=f"{label} フィルタ無し(member基準)")
    )
    # (2) 事後フィルタ：混入はしないが取りこぼす
    post = PostFilterRetriever(inner, MEMBER)
    results.append(
        sweep(lambda q, kk: post.search(q, k=kk), MEMBER, queries, k,
              label=f"{label} 事後フィルタ(member)")
    )
    # (3)(4) 事前フィルタ：権限ごとに全件
    for principal in (MEMBER, BOSS):
        aware = AccessAwareRetriever(inner, principal)
        results.append(
            sweep(lambda q, kk, r=aware: r.search(q, k=kk), principal, queries, k,
                  label=f"{label} 事前フィルタ({principal.role})")
        )
    return results


def report(results: list[SweepResult]) -> int:
    """結果を表示し、事前フィルタで混入があれば 1 を返す。"""
    print()
    for r in results:
        print("  " + r.line())
    failures = [r for r in results if "事前フィルタ" in r.label and not r.clean]
    for r in results:
        if r.examples:
            head = "（想定どおりの対照群）" if "フィルタ無し" in r.label else "（要修正）"
            print(f"\n  {r.label} の混入例{head}")
            for query_id, chunk_id, visibility in r.examples:
                print(f"    {query_id}  {chunk_id}  visibility={visibility}")
    return 1 if failures else 0


def main() -> int:
    use_dense = "--dense" in sys.argv
    queries = leak_test_queries()
    print(f"検査クエリ {len(queries)} 件（業務クエリ＋プローブ）／ k={K}")

    results = run_all(lexical_index(), "bm25", queries)
    if use_dense:
        results += run_all(dense_index(), "dense", queries)

    code = report(results)
    print(
        "\n判定: "
        + ("混入あり。フィルタの実装を直してください。" if code
           else "事前フィルタの条件では混入0件でした。")
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
