#!/usr/bin/env python3
"""合成クエリログ（corpus/query_log.jsonl）から運用指標を集計する。

  python src/session17/metrics.py                 # すべて
  python src/session17/metrics.py --section counts
  python src/session17/metrics.py --section types
  python src/session17/metrics.py --section tail
  python src/session17/metrics.py --section latency

ログは tools/make_corpus.py が固定シードで生成する合成データなので、
ここで出る集計値は何度実行しても同じになる（src/session17/verify.py が固定している）。
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

SANDBOX_ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = SANDBOX_ROOT / "corpus" / "query_log.jsonl"

# 回答可能な型（Recall を定義できる型）。unanswerable は適合文書が存在しない
ANSWERABLE_TYPES: tuple[str, ...] = (
    "natural", "keyword", "abbrev", "multi_condition", "temporal",
)


def load_log(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path is not None else LOG_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"{p} がありません。先に `python tools/make_corpus.py` を実行してください。"
        )
    with p.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def percentile(values: list[int | float], q: float) -> float:
    """最近傍順位法のパーセンタイル（外部ライブラリを使わない）。"""
    if not values:
        raise ValueError("空の配列にはパーセンタイルがありません")
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return float(ordered[rank - 1])


def query_counts(log: list[dict]) -> Counter:
    return Counter(r["query_id"] for r in log)


def rows_by_type(log: list[dict]) -> dict[str, int]:
    counts = Counter(r["query_type"] for r in log)
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def cumulative_share(log: list[dict], k: int) -> int:
    """頻度上位 k クエリが占める行数。"""
    counts = query_counts(log)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return sum(c for _, c in ordered[:k])


def summarize(log: list[dict]) -> dict:
    n = len(log)
    counts = query_counts(log)
    zero = [r for r in log if r["n_results"] == 0]
    with_results = [r for r in log if r["n_results"] > 0]
    clicked = [r for r in log if r.get("clicked_rank")]
    no_click = [r for r in with_results if not r.get("clicked_rank")]
    latencies = [r["latency_ms"] for r in log]
    top10 = cumulative_share(log, 10)
    manager = sum(1 for r in log if r.get("user_role") == "manager")
    return {
        "rows": n,
        "distinct_queries": len(counts),
        "singleton_queries": sum(1 for c in counts.values() if c == 1),
        "zero_hits": len(zero),
        "zero_hit_rate": len(zero) / n,
        "clicked": len(clicked),
        "click_rate": len(clicked) / n,
        "rows_with_results": len(with_results),
        "no_click": len(no_click),
        "no_click_rate": len(no_click) / len(with_results),
        "top10_rows": top10,
        "top10_share": top10 / n,
        "manager_rows": manager,
        "manager_share": manager / n,
        "latency_p50": percentile(latencies, 0.50),
        "latency_p95": percentile(latencies, 0.95),
        "latency_min": min(latencies),
        "latency_max": max(latencies),
    }


def print_counts(log: list[dict]) -> None:
    s = summarize(log)
    print("=== 規模 ===")
    print(f"ログ件数 : {s['rows']}")
    print(f"クエリの種類数 : {s['distinct_queries']}")
    print(f"1回しか出ていないクエリ : {s['singleton_queries']}")
    print(f"上位10クエリの行数 : {s['top10_rows']}（全体の {s['top10_share'] * 100:.1f}%）")
    print(f"管理職ロールの行数 : {s['manager_rows']}（全体の {s['manager_share'] * 100:.1f}%）")
    print("=== 失敗シグナル ===")
    print(f"ゼロヒット : {s['zero_hits']} 行（{s['zero_hit_rate'] * 100:.1f}%）")
    print(f"クリックあり : {s['clicked']} 行（{s['click_rate'] * 100:.1f}%）")
    print(f"結果はあったがクリック無し : {s['no_click']} 行"
          f"（結果があった {s['rows_with_results']} 行の {s['no_click_rate'] * 100:.1f}%）")


def print_types(log: list[dict]) -> None:
    n = len(log)
    print("=== クエリ型別の行数（＝本番での需要）===")
    for qtype, rows in rows_by_type(log).items():
        print(f"{qtype} : {rows} 行（{rows / n * 100:.1f}%）")


def print_tail(log: list[dict]) -> None:
    counts = query_counts(log)
    texts = {r["query_id"]: r["text"] for r in log}
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    print("=== 頻出クエリ（上位5件）===")
    for rank, (qid, rows) in enumerate(ordered[:5], start=1):
        print(f"{rank}位 {qid} {rows} 行 : {texts[qid]}")
    print("=== 累積カバー率 ===")
    n = len(log)
    for k in (5, 10, 20, 36):
        rows = cumulative_share(log, k)
        print(f"上位{k}クエリ : {rows} 行（{rows / n * 100:.1f}%）")


def print_latency(log: list[dict]) -> None:
    s = summarize(log)
    print("=== レイテンシ（合成値。手元の出力を記録してください）===")
    print(f"p50 : {s['latency_p50']:.0f} ms")
    print(f"p95 : {s['latency_p95']:.0f} ms")
    print(f"最小 / 最大 : {s['latency_min']} ms / {s['latency_max']} ms")


def main() -> None:
    parser = argparse.ArgumentParser(description="検索ログから運用指標を集計する")
    parser.add_argument("--section", default="all",
                        choices=["all", "counts", "types", "tail", "latency"])
    parser.add_argument("--log", default=None, help="ログのパス（既定: corpus/query_log.jsonl）")
    args = parser.parse_args()

    log = load_log(args.log)
    sections = {
        "counts": print_counts, "types": print_types,
        "tail": print_tail, "latency": print_latency,
    }
    if args.section == "all":
        for name, fn in sections.items():
            fn(log)
            print()
    else:
        sections[args.section](log)


if __name__ == "__main__":
    main()
