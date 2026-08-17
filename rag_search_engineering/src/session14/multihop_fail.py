#!/usr/bin/env python3
"""チャンク検索が構造的に解けない質問を、失敗させて見せる。

  docker compose exec app python src/session14/multihop_fail.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph_lab import CANDIDATE_K, CONTEXT_K, MULTIHOP_QUESTIONS, Bench, hop_report  # noqa: E402


def yesno(flag: bool) -> str:
    return "はい" if flag else "いいえ"


def main() -> None:
    bench = Bench()
    print("=== マルチホップ質問：上位10件では答えに届かない ===")
    print(f"チャンク {len(bench.chunks)} 件（fixed 400/80）/ 参照エッジ {len(bench.graph.edges)} 本")
    print(f"コンテキストに渡す件数 {CONTEXT_K} / 候補集合 {CANDIDATE_K}\n")

    answered = 0
    for q in MULTIHOP_QUESTIONS:
        r = hop_report(bench, q)
        answered += int(r["answer_in_top"])
        print(f"[{q.qid}] {q.text}")
        print(f"  答えの所在        : {bench.graph.label(r['answer'])}")
        print(f"                      「{q.fact}」")
        print(f"  上位{CONTEXT_K}件に答えが載ったか : {yesno(r['answer_in_top'])}")
        print(f"  起点になる文書    : {bench.graph.label(r['bridge'])}")
        print(f"  起点が候補{CANDIDATE_K}件に入ったか : {yesno(r['bridge_in_cand'])}")
        if r["path"]:
            hops = len(r["path"]) - 1
            print(f"  文書をまたぐ経路  : {' -> '.join(r['path'])}（{hops}ホップ）")
        print(f"  上位{CONTEXT_K}件の文書  : {', '.join(r['top_docs'])}")
        print()

    print(f"答えが上位{CONTEXT_K}件に載った質問: {answered} / {len(MULTIHOP_QUESTIONS)}")
    print("質問の語と答えの文書の語が1つも重ならないため、語彙一致でも意味の近さでも上位に来ません。")
    print("リランクでは救えない型の失敗です。手がかりは文書間の参照だけです。")


if __name__ == "__main__":
    main()
