#!/usr/bin/env python3
"""集約質問（「何件あるか」）は検索でもグラフでもなく、メタデータの集計で解く。

  docker compose exec app python src/session14/aggregate.py
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph_lab import CONTEXT_K, Bench  # noqa: E402

CATEGORIES = ("PC・端末", "アカウント", "オフィス", "セキュリティ", "勤怠", "経費")
SOURCE_TYPES = ("faq", "notice", "policy", "procedure")


def category_counts(docs) -> dict[str, int]:
    return dict(sorted(Counter(d.category for d in docs).items()))


def source_type_counts(docs) -> dict[str, int]:
    return dict(sorted(Counter(d.source_type for d in docs).items()))


def dept_counts(docs) -> dict[str, int]:
    return dict(sorted(Counter(d.dept for d in docs).items()))


def cross_tab(docs) -> dict[str, dict[str, int]]:
    """カテゴリ × 種別のクロス集計。コミュニティ要約の代わりに使える索引カード。"""
    table: dict[str, dict[str, int]] = defaultdict(lambda: {t: 0 for t in SOURCE_TYPES})
    for d in docs:
        table[d.category][d.source_type] += 1
    return {cat: table[cat] for cat in sorted(table)}


def main() -> None:
    bench = Bench()
    docs = bench.docs

    print("=== 集約質問は上位k件からは答えられない ===")
    question = "セキュリティに関する文書は全部で何件ありますか"
    hits = bench.search_docs(question, k=CONTEXT_K)
    print(f"質問: {question}")
    print(f"  検索で得られる文書   : {len(hits)} 件（上位{CONTEXT_K}件を文書に畳んだ数）")
    print("  → 上位k件は「k件しか返さない」ので、件数を数える材料になりません。")
    print("  → グラフを足しても同じです。全件を見ないと数えられない質問だからです。")

    counts = category_counts(docs)
    print(f"  メタデータの集計だと : セキュリティ {counts['セキュリティ']} 件（正確）")

    print("\nカテゴリ別")
    for cat, n in counts.items():
        print(f"  {cat:<12}: {n}")
    print("\n種別別")
    for st, n in source_type_counts(docs).items():
        print(f"  {st:<12}: {n}")
    print("\n所管部署別")
    for dept, n in dept_counts(docs).items():
        print(f"  {dept:<12}: {n}")

    print("\nカテゴリ × 種別（コミュニティ要約の代わりに置く索引カード）")
    header = "  " + " " * 14 + "".join(f"{t:>10}" for t in SOURCE_TYPES) + f"{'計':>8}"
    print(header)
    for cat, row in cross_tab(docs).items():
        line = f"  {cat:<14}" + "".join(f"{row[t]:>10}" for t in SOURCE_TYPES)
        print(line + f"{sum(row.values()):>8}")

    print("\n=== 「規程」と名の付く文書は何件か ===")
    policies = [d for d in docs if d.source_type == "policy"]
    named = [d for d in policies if d.title.split("（")[0].endswith("規程")]
    print(f"  source_type=policy : {len(policies)} 件")
    print(f"  タイトルが規程で終わる: {len(named)} 件")
    print(f"  差の {len(policies) - len(named)} 件は補則と運用細則。"
          "「規程は何件か」は聞き手の定義で答えが変わります。")
    print("  集約質問は、数える前に「何を1件と数えるか」を決める必要があります。")


if __name__ == "__main__":
    main()
