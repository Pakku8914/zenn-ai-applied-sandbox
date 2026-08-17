#!/usr/bin/env python3
"""型ごとに打ち手を割り当て、効果とコスト（回数）を同じ表で見る。

    python src/session10/route_lab.py

打ち手の割り当ては「abbrev は辞書展開 / multi_condition は分解 / 他は素通し」。
LLM は1回も呼ばない構成である。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from query_lab import TypeRouter, call_plan  # noqa: E402

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

TYPES = ("abbrev", "keyword", "multi_condition", "natural", "temporal")
ACTIONS = {
    "abbrev": "同義語辞書でクエリ側展開",
    "keyword": "そのまま（何もしない）",
    "multi_condition": "サブ質問に分解して RRF で統合",
    "natural": "そのまま（何もしない）",
    "temporal": "そのまま（鮮度の扱いは S13・S16）",
}
REPORT_DIR = Path(__file__).resolve().parents[2] / "reports"


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    index = LexicalIndex().build(chunk_all(docs, "fixed", size=400, overlap=80))
    router = TypeRouter(index, candidates=20)

    rep_base = evaluate(index, queries, qrels, k=10, label="bm25 / fixed")
    rep_router = evaluate(router, queries, qrels, k=10, label="bm25 / fixed + 型別の打ち手")

    print("=== 1. 型ごとの打ち手と効果（Recall@10 / 110クエリ）===")
    print(f"{'type':<18}{'n':>5}{'base':>10}{'routed':>10}  action")
    for t in TYPES:
        b, a = rep_base.by_type[t], rep_router.by_type[t]
        print(f"{t:<18}{int(b['n_queries']):>5}{b['recall']:>10.3f}{a['recall']:>10.3f}  {ACTIONS[t]}")
    print(f"{'ALL':<18}{int(rep_base.macro['n_queries']):>5}"
          f"{rep_base.macro['recall']:>10.3f}{rep_router.macro['recall']:>10.3f}")

    print("\n=== 2. 分類の内訳（ルーターが見たクエリ）===")
    print({t: router.stats[t] for t in TYPES})

    print("\n=== 3. コスト（回数で数える）===")
    print(f"検索の実行回数: {router.searches} 回（110 + 複数条件12件のぶん）")
    print(f"LLM 呼び出し  : {router.llm_calls} 回")
    print("参考: LLM に書き換えさせる場合の呼び出し回数（本番は回答不能クエリも来るので120件で数える）")
    print(f"  全クエリを書き換える      : {call_plan(queries)['ALL']} 回")
    print(f"  略語クエリだけ書き換える  : {call_plan(queries, {'abbrev'})['ALL']} 回")
    print(f"  略語と複数条件だけ        : {call_plan(queries, {'abbrev', 'multi_condition'})['ALL']} 回")

    rep_router.to_json(REPORT_DIR / "s10_router.json")
    print("\n-> reports/s10_router.json")


if __name__ == "__main__":
    main()
