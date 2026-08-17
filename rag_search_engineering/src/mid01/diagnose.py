#!/usr/bin/env python3
"""基準線の診断票：失敗を「到達不足」と「順位不足」に分解する（Review01 の道具）。

  到達不足 = 1 − Recall@100          そもそも上位100件にすら入っていない
  順位不足 = Recall@100 − Recall@10  入っているのに10位以内に来ていない
  Recall@10 ＋ 順位不足 ＋ 到達不足 = 1（恒等式）

どちらが主因かで、次に打つ手が変わる。到達不足には「拾える語を増やす」施策、
順位不足には「並べ替える」施策。診断せずに施策を選ぶと、効かない側を磨くことになる。

密ベクトルを使わないので、埋め込みモデル無しで数秒で終わる。

  python src/mid01/diagnose.py
  python src/mid01/diagnose.py --deep 50   # 到達の上限を測る深さを変える
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from faq_search import BASE_METHOD, BASELINE, build_chunks, build_lexical  # noqa: E402

from ragkit.corpus import load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402

TYPES = ("abbrev", "keyword", "multi_condition", "natural", "temporal")


def split_failures(rep_k, rep_deep) -> dict[str, dict[str, float]]:
    """型ごと（と全体）に Recall を到達不足・順位不足へ分解する。"""
    rows: dict[str, dict[str, float]] = {}
    for t in TYPES:
        shallow, deep = rep_k.by_type[t], rep_deep.by_type[t]
        rows[t] = _row(shallow["n_queries"], shallow["recall"], deep["recall"])
    rows["ALL"] = _row(rep_k.macro["n_queries"], rep_k.macro["recall"], rep_deep.macro["recall"])
    return rows


def _row(n: float, shallow: float, deep: float) -> dict[str, float]:
    return {
        "n": n,
        "recall_k": shallow,
        "recall_deep": deep,
        "rank_gap": deep - shallow,   # 順位不足
        "reach_gap": 1.0 - deep,      # 到達不足
    }


def main_cause(row: dict[str, float]) -> str:
    """主因が到達側か順位側かを言い切る。

    全体（ALL）は両者が打ち消し合って「拮抗」に見えることがある。
    そのときこそ型別に降りる必要がある、というのがこの表の使い方。
    """
    if row["rank_gap"] + row["reach_gap"] < 0.05:
        return "問題なし（残っている失敗が小さい）"
    diff = row["reach_gap"] - row["rank_gap"]
    if diff > 0.05:
        return "到達側（そもそも拾えていない）"
    if diff < -0.05:
        return "順位側（拾えているが上位に来ない）"
    return "拮抗（型別に降りて判断する）"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10, help="運用で使う件数")
    ap.add_argument("--deep", type=int, default=100, help="到達の上限を測る深さ")
    args = ap.parse_args()

    queries, qrels = load_queries(), load_qrels()
    lex = build_lexical(build_chunks(BASE_METHOD))
    rep_k = evaluate(lex, queries, qrels, k=args.k, label=BASELINE)
    rep_deep = evaluate(lex, queries, qrels, k=args.deep, label=f"{BASELINE} (k={args.deep})")
    rows = split_failures(rep_k, rep_deep)

    print(f"### 基準線の診断票（{BASELINE}・チャンク方式 {BASE_METHOD}）\n")
    print(f"| クエリ型 | n | Recall@{args.k} | Recall@{args.deep} | 順位不足 | 到達不足 | 主因 |")
    print("| :--- | --: | --: | --: | --: | --: | :--- |")
    for name, r in rows.items():
        print(
            f"| {name} | {int(r['n'])} | {r['recall_k']:.3f} | {r['recall_deep']:.3f} "
            f"| {r['rank_gap']:.3f} | {r['reach_gap']:.3f} | {main_cause(r)} |"
        )

    total = rows["ALL"]
    print(
        f"\n上位{args.deep}件を完璧に並べ替えられたとしても、Recall@{args.k} の上限は "
        f"{total['recall_deep']:.3f} です（到達不足 {total['reach_gap']:.3f} は並べ替えでは動きません）。"
    )
    print("\n1クエリが平均を動かす幅（この幅より小さい差を『改善』と呼ばない）:")
    for name in ("ALL", *TYPES):
        n = int(rows[name]["n"])
        print(f"  {name:<16} n={n:>3}  1クエリあたり ±{1 / n:.3f}")


if __name__ == "__main__":
    main()
