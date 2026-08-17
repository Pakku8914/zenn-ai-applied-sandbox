#!/usr/bin/env python3
"""「RAG の精度が低い」を3層（コーパス / 検索 / 生成）に割る。

    python src/session12/triage.py

出力:
  1. 層別の件数（クエリ型ごとの内訳つき）
  2. 失敗ケースの一覧（先頭20件）――上限測定にかける対象
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_lab import LAYERS, Bench, collect_cases, layer_counts  # noqa: E402

from ragkit.llm import FixtureClient  # noqa: E402

LABEL = {"ok": "成功", "corpus": "コーパス起因", "retrieval": "検索起因", "generation": "生成起因"}


def reason(case) -> str:
    """なぜその層になったのかを1行で言う。分類の根拠を残さないと議論できない。"""
    j = case.judgement
    if case.layer == "corpus":
        return "適合文書がコーパスに無く、回答不能と判定した（打ち手はコーパス）"
    if case.layer == "retrieval":
        return f"適合文書が1件も届いていない（上位{case.n_hits}件・完全適合0件）"
    if not j.answerable:
        return f"適合文書が{case.relevant_in_context}件届いているのに回答不能と答えた"
    if not j.has_citation:
        return "引用が付いていない"
    if not j.citations_valid:
        return f"存在しない chunk_id を引用した: {j.invalid_citations}"
    if not j.grounded:
        return "引用先が判定データ上の適合文書ではない"
    return "検査を通過"


def main() -> None:
    bench = Bench()
    cases = collect_cases(bench, FixtureClient("answers_v1"))

    counts = layer_counts(cases)
    total = len(cases)
    print(f"対象クエリ {total} 件（回答可能 {len(bench.answerable_queries())} / "
          f"回答不能 {total - len(bench.answerable_queries())}）")
    print("\n--- 層別の件数 ---")
    for layer in LAYERS:
        n = counts[layer]
        print(f"{LABEL[layer]:<12} {n:>3} 件  ({n / total:.1%})")

    print("\n--- クエリ型 × 層 ---")
    types = sorted({c.query_type for c in cases})
    header = "型".ljust(16) + "".join(LABEL[layer].rjust(14) for layer in LAYERS)
    print(header)
    for t in types:
        row = Counter(c.layer for c in cases if c.query_type == t)
        print(t.ljust(16) + "".join(str(row.get(layer, 0)).rjust(14) for layer in LAYERS))

    failures = [c for c in cases if c.layer != "ok"]
    print(f"\n--- 失敗ケース {len(failures)} 件のうち先頭20件 ---")
    for c in failures[:20]:
        print(f"{c.query_id}  {c.query_type:<15} {LABEL[c.layer]:<12} {reason(c)}")
    print("\nこの20件を上限測定にかけて、分類が正しいかを確かめる: "
          "python src/session12/upper_bound.py")


if __name__ == "__main__":
    main()
