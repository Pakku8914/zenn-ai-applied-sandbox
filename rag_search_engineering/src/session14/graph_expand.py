#!/usr/bin/env python3
"""グラフ探索と検索を組み合わせて、回答に必要な文書集合を集める。

  docker compose exec app python src/session14/graph_expand.py

型を指定しない拡張（全部の参照を辿る）と、delegates_to だけを辿る拡張を比べる。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph_lab import CANDIDATE_K, MULTIHOP_QUESTIONS, Bench, hop_report  # noqa: E402


def yesno(flag: bool) -> str:
    return "はい" if flag else "いいえ"


def main() -> None:
    bench = Bench()
    g = bench.graph
    print("=== 候補集合をグラフで広げる ===")
    print(f"候補は上位{CANDIDATE_K}チャンクを文書に畳んだもの。そこから1ホップだけ辿る。\n")

    reached = 0
    for q in MULTIHOP_QUESTIONS:
        r = hop_report(bench, q)
        reached += int(r["answer_reached"])
        print(f"[{q.qid}] {q.text}")
        print(f"  候補の文書数              : {len(r['cand_docs'])}")
        print(f"  型を指定しない1ホップ拡張 : +{r['added_untyped']} 件")
        print(f"  delegates_to だけの拡張   : +{r['added_typed']} 件")
        print(f"  答えの文書に到達したか    : {yesno(r['answer_reached'])}"
              f"（{g.label(r['answer'])}）")
        print(f"  経路                      : {' -> '.join(r['path']) if r['path'] else '（なし）'}")
        print()

    print(f"delegates_to の1ホップで答えに到達した質問: {reached} / {len(MULTIHOP_QUESTIONS)}")
    print()
    print("--- 型を指定しないとどうなるか（MH-01 で確認）---")
    q = MULTIHOP_QUESTIONS[0]
    r = hop_report(bench, q)
    cand = set(r["cand_docs"])
    untyped = g.expand(cand, hops=1)
    typed = g.expand(cand, hops=1, kinds=("delegates_to",))
    added = sorted(untyped - cand)
    print(f"型なしで増えた文書 {len(added)} 件。"
          f"うち答えの文書（{r['answer']}）が混ざっているか: {yesno(r['answer'] in added)}")
    print("増えた文書の内訳（先頭5件）:")
    for doc_id in added[:5]:
        print(f"  {g.label(doc_id)}")
    print(f"型ありで増えた文書 {len(typed - cand)} 件:")
    for doc_id in sorted(typed - cand):
        print(f"  {g.label(doc_id)}")
    print()
    print("--- 2ホップに増やすとどうなるか ---")
    for hops in (1, 2, 3):
        size = len(g.expand(cand, hops=hops))
        print(f"  {hops} ホップ: {size} 文書（候補 {len(cand)} 件から）")
    print("ホップを増やすほどコンテキストの予算を食い、関係の薄い文書が混ざります。")


if __name__ == "__main__":
    main()
