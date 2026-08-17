#!/usr/bin/env python3
"""検索指標（Recall@10）と回答の成否がどれだけ連動するかを見る。

    python src/session12/correlate.py

検索の数字を「回答品質の代理指標」として使ってよいのかを確かめる手続きである。
連動していなければ、Recall を上げても報告される体感は変わらない。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_lab import Bench, collect_cases, pearson  # noqa: E402

from ragkit.eval import evaluate  # noqa: E402
from ragkit.llm import FixtureClient  # noqa: E402

BUCKETS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01))


def main() -> None:
    bench = Bench()
    rep = evaluate(bench.index, bench.queries, bench.qrels, k=10, label="bm25/fixed")
    cases = {c.query_id: c for c in collect_cases(bench, FixtureClient("answers_v1"))}

    pairs = [(rep.per_query[qid]["recall"], cases[qid]) for qid in rep.per_query if qid in cases]
    recalls = [r for r, _ in pairs]
    success = [1.0 if c.layer == "ok" else 0.0 for _, c in pairs]
    faith = [c.judgement.faithfulness for _, c in pairs]

    print(f"対象 {len(pairs)} 件（回答可能クエリのみ。回答不能クエリは Recall が定義できない）")
    print(f"Recall@10 の平均       : {sum(recalls) / len(recalls):.3f}")
    print(f"回答が成功した割合     : {sum(success) / len(success):.3f}")
    print(f"相関 r（Recall@10 × 回答成功）  : {pearson(recalls, success):+.3f}")
    print(f"相関 r（Recall@10 × 忠実性）    : {pearson(recalls, faith):+.3f}")

    print("\n--- Recall@10 の帯ごとの回答成功率 ---")
    print("Recall@10".ljust(14) + "件数".rjust(6) + "回答成功".rjust(10) + "成功率".rjust(10))
    for lo, hi in BUCKETS:
        rows = [(r, c) for r, c in pairs if lo <= r < hi]
        if not rows:
            print(f"[{lo:.1f}, {min(hi, 1.0):.1f})".ljust(14) + "0".rjust(6) + "-".rjust(10) + "-".rjust(10))
            continue
        ok = sum(1 for _, c in rows if c.layer == "ok")
        print(f"[{lo:.1f}, {min(hi, 1.0):.1f})".ljust(14) + str(len(rows)).rjust(6)
              + str(ok).rjust(10) + f"{ok / len(rows):.1%}".rjust(10))

    high_fail = [(r, c) for r, c in pairs if r >= 0.8 and c.layer != "ok"]
    low_ok = [(r, c) for r, c in pairs if r <= 0.2 and c.layer == "ok"]
    print(f"\nRecall@10 が 0.8 以上なのに回答が失敗: {len(high_fail)} 件")
    for r, c in high_fail[:5]:
        print(f"  {c.query_id} ({c.query_type}) Recall={r:.3f} 層={c.layer}")
    print(f"Recall@10 が 0.2 以下なのに回答が成功: {len(low_ok)} 件")
    for r, c in low_ok[:5]:
        print(f"  {c.query_id} ({c.query_type}) Recall={r:.3f} 完全適合が届いた数={c.gold_in_context}")
    print("\nこの2つの箱に入る件数が、代理指標として使うときの誤差の正体である。")


if __name__ == "__main__":
    main()
