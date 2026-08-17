#!/usr/bin/env python3
"""グラフを使わない代替策と突き合わせる（親子チャンク／参照追跡＝多段検索）。

  docker compose exec app python src/session14/alternatives.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph_lab import (  # noqa: E402
    CANDIDATE_K,
    CONTEXT_K,
    MULTIHOP_QUESTIONS,
    Bench,
    candidate_expressions,
    mention_kind,
)


def parent_child_hits(bench: Bench, q, k: int = CONTEXT_K) -> bool:
    """親子チャンク：子で検索し、親（前後を含む広い範囲）を読ませる。"""
    return q.fact in bench.parent_context(q.text, k=k)


def followup_names(bench: Bench, doc_ids, kinds=("delegates_to",)) -> list[str]:
    """検索で取れた文書の本文から、質問時に参照名を読み取る（事前構築なし）。"""
    names: list[str] = []
    for doc_id in doc_ids:
        doc = bench.by_id[doc_id]
        for name in candidate_expressions(doc):
            if mention_kind(doc, name) in kinds and name not in names:
                names.append(name)
    return names


def follow_references(bench: Bench, q, k: int = CANDIDATE_K):
    """参照追跡（多段検索）：1回目の結果に書かれた文書名で、もう1回検索する。"""
    first = bench.search_docs(q.text, k=k)
    names = followup_names(bench, first)
    reached: list[str] = list(first)
    for name in names:
        for doc_id in bench.search_docs(name, k=CONTEXT_K):
            if doc_id not in reached:
                reached.append(doc_id)
    return first, names, reached


def yesno(flag: bool) -> str:
    return "はい" if flag else "いいえ"


def main() -> None:
    bench = Bench()
    g = bench.graph
    print("=== 代替策との突き合わせ ===")
    print("A: 親子チャンク（子で検索し親で答える）")
    print("B: 参照追跡（1回目の結果に書かれた文書名で2回目を検索する多段検索）")
    print("C: 参照グラフ（delegates_to を1ホップ）\n")

    rows = []
    for q in MULTIHOP_QUESTIONS:
        a = parent_child_hits(bench, q)
        first, names, reached = follow_references(bench, q)
        b = bench.has_answer(reached, q.fact)
        cand = bench.search_docs(q.text, k=CANDIDATE_K)
        expanded = g.expand(cand, hops=1, kinds=("delegates_to",))
        c = bench.doc_id(q.answer_title) in expanded
        rows.append((q.qid, a, b, c, len(names)))
        print(f"[{q.qid}] {q.text}")
        print(f"  A 親子チャンクで答えに届いたか : {yesno(a)}")
        print(f"  B 参照追跡で答えに届いたか     : {yesno(b)}"
              f"（追加の検索 {len(names)} 回: {', '.join(names) if names else 'なし'}）")
        print(f"  C グラフ1ホップで届いたか      : {yesno(c)}")
        print()

    print("| 質問 | A 親子チャンク | B 参照追跡 | C グラフ | B の追加検索 |")
    print("| :--- | :--- | :--- | :--- | ---: |")
    for qid, a, b, c, n in rows:
        print(f"| {qid} | {yesno(a)} | {yesno(b)} | {yesno(c)} | {n} |")

    print()
    print("親子チャンクは同じ文書の中しか広げられないので、文書をまたぐ質問には原理的に効きません。")
    print("参照追跡とグラフは同じ答えに届きます。違うのは、いつ費用を払うかです。")
    print("  参照追跡 : 事前構築 0 回。質問のたびに追加の検索が発生する（レイテンシ）")
    print("  グラフ   : 事前構築が必要。質問時は辞書引きだけ（更新のたびに作り直す）")


if __name__ == "__main__":
    main()
