#!/usr/bin/env python3
"""上限測定：正解チャンクを直接渡したら答えられるのかを確かめる。

    python src/session12/upper_bound.py

「検索起因だと思う」は仮説にすぎない。判定データから作った正解チャンクを渡して
それでも答えられないなら、直すべきは検索ではない。分類を反証するための手続きである。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_lab import LAYERS, MAX_CHARS, Bench, collect_cases  # noqa: E402
from make_gold_cassette import CASSETTE, build  # noqa: E402

from ragkit.answer import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from ragkit.llm import FixtureClient  # noqa: E402

LABEL = {"ok": "成功", "corpus": "コーパス起因", "retrieval": "検索起因", "generation": "生成起因"}


def gold_client(bench: Bench) -> FixtureClient:
    """上限測定用のカセットを開く。無ければその場で作る。"""
    try:
        return FixtureClient(CASSETTE)
    except FileNotFoundError:
        build(bench)
        return FixtureClient(CASSETTE)


def main() -> None:
    bench = Bench()
    retrieved = {c.query_id: c for c in collect_cases(bench, FixtureClient("answers_v1"))}
    upper = {c.query_id: c for c in collect_cases(bench, gold_client(bench), gold=True)}

    ok_r = sum(1 for c in retrieved.values() if c.layer == "ok")
    ok_g = sum(1 for c in upper.values() if c.layer == "ok")
    n = len(retrieved)
    print(f"検索結果を渡したとき : 成功 {ok_r}/{n} 件 ({ok_r / n:.1%})")
    print(f"正解チャンクを渡したとき（上限）: 成功 {ok_g}/{n} 件 ({ok_g / n:.1%})")
    print("この差が「検索を直しきったときに取り戻せる分」の上限になる。")

    print("\n--- 検索版の層ごとに、上限測定でどうなったか ---")
    print("元の層".ljust(14) + "件数".rjust(6) + "上限で成功".rjust(12) + "上限でも失敗".rjust(14))
    for layer in LAYERS:
        ids = [qid for qid, c in retrieved.items() if c.layer == layer]
        if not ids:
            continue
        fixed = sum(1 for qid in ids if upper[qid].layer == "ok")
        print(LABEL[layer].ljust(14) + str(len(ids)).rjust(6)
              + str(fixed).rjust(12) + str(len(ids) - fixed).rjust(14))

    stubborn = [qid for qid, c in retrieved.items()
                if c.layer == "retrieval" and upper[qid].layer != "ok"]
    print(f"\n検索起因と分類したのに上限測定でも直らなかった: {len(stubborn)} 件")
    for qid in stubborn[:5]:
        u = upper[qid].judgement
        why = ("回答不能と答えた" if not u.answerable else
               f"引用が無効: {u.invalid_citations}" if not u.citations_valid else
               "引用が付いていない" if not u.has_citation else "引用先が適合文書でない")
        print(f"  {qid}  正解チャンク {upper[qid].n_hits} 件を渡しても {why}")
    if stubborn:
        print("  → この分は検索を直しても取り戻せない。分類を『生成起因』に訂正する。")

    # カセットの管理コスト：コンテキストが変わればキーが変わる
    print("\n--- 合成カセットの管理コスト ---")
    old = FixtureClient("answers_v1")
    misses = 0
    for q in bench.queries[:30]:
        hits = bench.gold_hits(q)
        try:
            old.complete(SYSTEM_PROMPT, build_user_prompt(q.text, hits, max_chars=MAX_CHARS))
        except KeyError:
            misses += 1
    print(f"上限測定のプロンプトを answers_v1 に投げると {misses}/30 件が KeyError になる。")
    print("コンテキストを変えた時点で、カセットは1本増える。これが再現性の値段。")


if __name__ == "__main__":
    main()
