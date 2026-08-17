#!/usr/bin/env python3
"""成果物③：再現可能な評価スクリプト。

  python src/mid01/run_eval.py --stage chunk    # 段階1：チャンク方式（モデル不要）
  python src/mid01/run_eval.py --stage method   # 段階2：検索方式
  python src/mid01/run_eval.py --stage fusion   # 段階3：統合方式
  python src/mid01/run_eval.py                  # 3段階すべて（既定）

表は Markdown で出す。チューニング記録にそのまま貼れる形にしておくと、
数字を手で写す工程が消える（写し間違いは記録の信頼を一撃で壊す）。
実行時間のような環境依存の値は標準出力に出さず JSON にだけ残す。
標準出力が環境ごとに変わると「同じ結果になったか」を目で確かめられなくなるため。

結果は reports/mid01_eval.json に保存する（per_query 付き）。
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from faq_search import (  # noqa: E402
    ADOPTED,
    BASE_METHOD,
    BASELINE,
    DENSE,
    build_chunks,
    build_dense,
    build_lexical,
    chunk_conditions,
    fusion_conditions,
    method_conditions,
)

from ragkit.corpus import load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402

DEFAULT_OUT = "reports/mid01_eval.json"


def measure(conditions: dict, reps: dict, queries, qrels, k: int, title: str) -> None:
    """まだ測っていない条件だけを測り、Markdown の表で出す。

    同じ条件を二度測らないのは速さのためだけではない。「同じ名前の条件が
    二度出てきて値が違う」という、記録として最悪の事故を構造的に防ぐため。
    """
    for name, retriever in conditions.items():
        if name in reps:
            continue
        t0 = time.perf_counter()
        rep = evaluate(retriever, queries, qrels, k=k, label=name)
        rep.macro["elapsed_sec"] = round(time.perf_counter() - t0, 1)
        reps[name] = rep
    print(f"\n### {title}\n")
    print("| 条件 | Recall@10 | nDCG@10 | MRR | P@10 | abbrev | multi_condition |")
    print("| :--- | --: | --: | --: | --: | --: | --: |")
    for name in conditions:
        m, by = reps[name].macro, reps[name].by_type
        print(
            f"| {name} | {m['recall']:.3f} | {m['ndcg']:.3f} | {m['mrr']:.3f} "
            f"| {m['precision']:.3f} | {by['abbrev']['recall']:.3f} "
            f"| {by['multi_condition']['recall']:.3f} |"
        )


def route_table(reps: dict) -> None:
    """順路（基準線 → 検索方式 → 統合方式）の寄与を差分で出す。

    差分は「3桁に丸めた値どうしの差」にする。表に並んだ数字を読者が
    そのまま引き算した結果と、差分の列が食い違わないようにするため。
    """
    print("\n### 順路（各施策の寄与）\n")
    print("| 段階 | 条件 | Recall@10 | nDCG@10 | 前段からの差分 | 基準線からの差分 |")
    print("| :--- | :--- | --: | --: | --: | --: |")
    first = round(reps[BASELINE].macro["recall"], 3)
    prev: float | None = None
    for i, name in enumerate((BASELINE, DENSE, ADOPTED)):
        r = round(reps[name].macro["recall"], 3)
        n = round(reps[name].macro["ndcg"], 3)
        d_prev = "—" if prev is None else f"{r - prev:+.3f}"
        d_base = "—" if i == 0 else f"{r - first:+.3f}"
        print(f"| {i} | {name} | {r:.3f} | {n:.3f} | {d_prev} | {d_base} |")
        prev = r


def save(reps: dict, out: str, k: int) -> None:
    """per_query まで残す。あとから部分集合の平均を出すのに再測定が要らなくなる。"""
    path = Path(out)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project": "mid01",
        "k": k,
        "chunk_method": BASE_METHOD,
        "env": {
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "conditions": [
            {"label": n, "macro": r.macro, "by_type": r.by_type, "per_query": r.per_query}
            for n, r in reps.items()
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("chunk", "method", "fusion", "all"), default="all")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    queries, qrels = load_queries(), load_qrels()
    chunks = build_chunks(BASE_METHOD)
    lex = build_lexical(chunks)
    dense = build_dense(chunks) if args.stage in ("method", "fusion", "all") else None
    reps: dict = {}

    if args.stage in ("chunk", "all"):
        measure(chunk_conditions(), reps, queries, qrels, args.k,
                "段階1：チャンク方式を選ぶ（検索方式は BM25 に固定）")
    if args.stage in ("method", "all"):
        measure(method_conditions(lex, dense), reps, queries, qrels, args.k,
                "段階2：検索方式を選ぶ（チャンク方式は fixed に固定）")
    if args.stage in ("fusion", "all"):
        conds = {BASELINE: lex, DENSE: dense, **fusion_conditions(lex, dense)}
        measure(conds, reps, queries, qrels, args.k,
                "段階3：統合方式を選ぶ（束ねる検索器は段階2と同一）")

    if {BASELINE, DENSE, ADOPTED} <= set(reps):
        route_table(reps)
    save(reps, args.out, args.k)


if __name__ == "__main__":
    main()
