#!/usr/bin/env python3
"""コーパスの統計を出す。本文に書く数値はこの出力を転記する。"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402


def main() -> None:
    docs = load_docs()
    queries = load_queries()
    qrels = load_qrels()

    lens = [len(d.full_text) for d in docs]
    print("=== 文書 ===")
    print(f"文書数            : {len(docs)}")
    print(f"総文字数          : {sum(lens):,}")
    print(f"1文書の文字数     : 平均 {statistics.mean(lens):.0f} / 中央値 {statistics.median(lens):.0f} "
          f"/ 最小 {min(lens)} / 最大 {max(lens)}")
    print(f"カテゴリ別        : {dict(sorted(Counter(d.category for d in docs).items()))}")
    print(f"種別別            : {dict(sorted(Counter(d.source_type for d in docs).items()))}")
    print(f"公開範囲別        : {dict(sorted(Counter(d.visibility for d in docs).items()))}")
    print(f"更新日別          : {dict(sorted(Counter(d.updated_at for d in docs).items()))}")

    print("\n=== クエリ ===")
    print(f"クエリ数          : {len(queries)}")
    print(f"型別              : {dict(sorted(Counter(q.type for q in queries).items()))}")
    answerable = [q for q in queries if any(g >= 1 for g in qrels.get(q.query_id, {}).values())]
    print(f"回答可能なクエリ  : {len(answerable)}（回答不能 {len(queries) - len(answerable)}）")

    print("\n=== 判定データ（qrels）===")
    grades = Counter(g for per in qrels.values() for g in per.values())
    print(f"判定件数          : {sum(grades.values())}")
    print(f"適合度の分布      : {dict(sorted(grades.items()))}")
    rel_counts = [sum(1 for g in per.values() if g >= 1) for per in qrels.values()]
    rel_counts = [c for c in rel_counts if c > 0]
    print(f"1クエリの適合文書数: 平均 {statistics.mean(rel_counts):.1f} / 最小 {min(rel_counts)} "
          f"/ 最大 {max(rel_counts)}")

    log_path = Path(__file__).resolve().parent.parent / "corpus" / "query_log.jsonl"
    if log_path.exists():
        log = [json.loads(line) for line in log_path.open(encoding="utf-8")]
        zero = sum(1 for r in log if r["n_results"] == 0)
        clicked = sum(1 for r in log if r["clicked_rank"])
        print("\n=== クエリログ（合成）===")
        print(f"ログ件数          : {len(log)}")
        print(f"ゼロヒット率      : {zero / len(log) * 100:.1f}%")
        print(f"クリック率        : {clicked / len(log) * 100:.1f}%")


if __name__ == "__main__":
    main()
