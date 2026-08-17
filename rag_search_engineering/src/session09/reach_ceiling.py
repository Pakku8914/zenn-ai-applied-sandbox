#!/usr/bin/env python3
"""「リランクで救えるクエリ」と「救えないクエリ」を1件ずつ判定する。

リランクは候補プールの並べ替えしかできないので、到達できていない文書は
どれだけ賢く並べ替えても戻ってこない。その境目をクエリごとに数値で出す。

  到達不足 = 1 − Recall@C（候補プールにすら入っていない割合）
  順位不足 = Recall@C − Recall@10（プールには居るが上位10件に来ていない割合）

実行:  docker compose exec app python src/session09/reach_ceiling.py
      docker compose exec app python src/session09/reach_ceiling.py multi_condition 6 50
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import answerable, ceiling_recall, dense_index, load_all  # noqa: E402

from ragkit.eval import recall_at_k  # noqa: E402
from ragkit.rerank import CrossEncoderReranker  # noqa: E402

K = 10
EPS = 1e-9


def judge(before: float, after: float, ceiling: float) -> str:
    if ceiling <= before + EPS:
        return "救えない（到達不足。候補に居ない）"
    if after > before + EPS:
        return "救えた（順位不足を回収）"
    if after < before - EPS:
        return "悪化（並べ替えで適合文書が押し出された）"
    return "余地はあったが変わらなかった"


def main() -> None:
    qtype = sys.argv[1] if len(sys.argv) > 1 else "abbrev"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    candidates = int(sys.argv[3]) if len(sys.argv) > 3 else 50

    _docs, queries, qrels, chunks = load_all()
    subset = [q for q in answerable(queries, qrels)
              if qtype == "all" or q.type == qtype][:limit]
    if not subset:
        raise SystemExit(f"クエリ型 {qtype} のクエリが見つかりません")

    dense = dense_index(chunks)
    CrossEncoderReranker.get()
    print(f"対象: {qtype} {len(subset)}件 / 1段目 dense / 候補{candidates}件\n")

    rows = []
    for q in subset:
        qr = qrels[q.query_id]
        base = dense.search(q.text, k=K)
        pool = dense.search(q.text, k=candidates)
        after = CrossEncoderReranker.rerank(q.text, pool, top_k=K)

        before_r = recall_at_k(base, qr, K)
        pool_r = recall_at_k(pool, qr, len(pool))
        after_r = recall_at_k(after, qr, K)
        ceiling = ceiling_recall(pool, qr, K)
        rows.append((before_r, pool_r, after_r, ceiling))

        print(f"{q.query_id} [{q.type}] {q.text}")
        print(f"  Recall@{K}(1段目)={before_r:.3f}  到達不足={1 - pool_r:.3f}  "
              f"順位不足={pool_r - before_r:.3f}  上限={ceiling:.3f}")
        print(f"  リランク後 Recall@{K}={after_r:.3f}（差 {after_r - before_r:+.3f}）  "
              f"判定: {judge(before_r, after_r, ceiling)}")

    n = len(rows)
    print(f"\n=== {qtype} {n}件の平均 ===")
    print(f"  Recall@{K}(1段目) : {sum(r[0] for r in rows) / n:.3f}")
    print(f"  到達不足          : {sum(1 - r[1] for r in rows) / n:.3f}"
          "   <- リランクでは絶対に減らせない")
    print(f"  順位不足          : {sum(r[1] - r[0] for r in rows) / n:.3f}"
          "   <- リランクが触れるのはここだけ")
    print(f"  Recall@{K}(リランク後) : {sum(r[2] for r in rows) / n:.3f}")
    saved = sum(1 for b, _p, a, c in rows if c > b + EPS and a > b + EPS)
    hopeless = sum(1 for b, _p, _a, c in rows if c <= b + EPS)
    print(f"  救えたクエリ {saved} 件 / 原理的に救えないクエリ {hopeless} 件 / 全 {n} 件")


if __name__ == "__main__":
    main()
