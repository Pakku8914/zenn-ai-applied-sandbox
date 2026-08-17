#!/usr/bin/env python3
"""問題6：クエリ型ごとに設定を切り替える「オラクル」の上限と、その数字の信用度を測る。

型ごとに最良の条件を選べばどこまで上がるかを測り、
そのうえで「学習用と検証用に分けたら、その改善は残るのか」を確かめます。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fusion_lab import TypeRoutedRetriever, build_indexes, subset_mean  # noqa: E402
from hybrid_recover import build_conditions, run_all  # noqa: E402

from ragkit.corpus import load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402

TYPES = ("abbrev", "keyword", "multi_condition", "natural", "temporal")
CANDIDATES = [
    "bm25 単体",
    "dense 単体",
    "rrf(候補50, rrf_k=60)",
    "minmax(候補50, 1.0:1.0)",
    "minmax(候補50, 0.3:1.0)",
]
FALLBACK = "minmax(候補50, 0.3:1.0)"


def qids_by_type(reps, queries) -> dict[str, list[str]]:
    """評価に含まれた（＝回答可能な）クエリIDを型別に集める。"""
    any_rep = next(iter(reps.values()))
    out: dict[str, list[str]] = {t: [] for t in TYPES}
    for q in queries:
        if q.query_id in any_rep.per_query and q.type in out:
            out[q.type].append(q.query_id)
    return out


def best_by_type(reps, groups: dict[str, list[str]], metric: str = "recall") -> dict[str, str]:
    """型ごとに、候補条件の中で最も成績の良いものを選ぶ（同点なら候補リストの先頭）。"""
    return {
        t: max(CANDIDATES, key=lambda name: subset_mean(reps[name], qids, metric))
        for t, qids in groups.items() if qids
    }


def routed_mean(reps, groups: dict[str, list[str]], choice: dict[str, str],
                metric: str = "recall") -> float:
    """選んだ条件で型別に測ったときの全体平均（検索を追加せず per_query から作る）。"""
    total, n = 0.0, 0
    for t, qids in groups.items():
        rep = reps[choice.get(t, FALLBACK)]
        for qid in qids:
            total += rep.per_query[qid][metric]
            n += 1
    return total / n if n else 0.0


def main() -> None:
    _, _, lex, dense = build_indexes()
    queries, qrels = load_queries(), load_qrels()
    reps = run_all(lex, dense, queries, qrels)
    groups = qids_by_type(reps, queries)

    print("--- 条件 × クエリ型の Recall@10 ---")
    header = "".join(f"{t[:12]:>16}" for t in TYPES)
    print(f"{'条件':<26}{header}{'件数合計':>10}")
    for name in CANDIDATES:
        row = "".join(f"{subset_mean(reps[name], groups[t]):>16.3f}" for t in TYPES)
        print(f"{name:<26}{row}{len(reps[name].per_query):>10}")
    print("件数" + "".join(f"{len(groups[t]):>16}" for t in TYPES))

    choice = best_by_type(reps, groups)
    print("\n--- 型ごとに最良を選ぶ（オラクル）---")
    for t in TYPES:
        print(f"  {t:<16}-> {choice[t]}")

    expected = routed_mean(reps, groups, choice)
    type_of = {q.text: q.type for q in queries}
    conditions = build_conditions(lex, dense)
    routed = TypeRoutedRetriever(
        {t: conditions[name] for t, name in choice.items()},
        default=conditions[FALLBACK],
        type_of=type_of,
    )
    rep_routed = evaluate(routed, queries, qrels, k=10, label="型別ルーティング（オラクル）")
    print(f"\n  per_query から計算した期待値: {expected:.3f}")
    print(f"  実際に検索して測った値      : {rep_routed.macro['recall']:.3f}")
    best_fixed = max(CANDIDATES, key=lambda n: reps[n].macro["recall"])
    print(f"  固定設定の最良 [{best_fixed}]: {reps[best_fixed].macro['recall']:.3f}")

    print("\n--- 同じ改善が、見ていないクエリでも出るか（学習用と検証用に分ける）---")
    train = {t: qids[0::2] for t, qids in groups.items()}
    test = {t: qids[1::2] for t, qids in groups.items()}
    choice_train = best_by_type(reps, train)
    fixed_train = max(
        CANDIDATES,
        key=lambda n: subset_mean(reps[n], [q for qs in train.values() for q in qs]),
    )
    test_ids = [q for qs in test.values() for q in qs]
    print(f"  学習側で選んだ型別設定: "
          f"{ {t: choice_train.get(t) for t in TYPES} }")
    print(f"  学習側で選んだ固定設定: {fixed_train}")
    print(f"  学習側での改善: "
          f"{routed_mean(reps, train, choice_train) - subset_mean(reps[fixed_train], [q for qs in train.values() for q in qs]):+.3f}")
    print(f"  検証側での改善: "
          f"{routed_mean(reps, test, choice_train) - subset_mean(reps[fixed_train], test_ids):+.3f}")
    print("  検証側の改善が学習側より小さければ、その差は詰めすぎ（過学習）の分です")


if __name__ == "__main__":
    main()
