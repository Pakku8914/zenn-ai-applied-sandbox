#!/usr/bin/env python3
"""セッション2 問題9の解答：reports/ の JSON を1枚の表に畳み、SLO で判定する。

    docker compose exec app python tools/bench_serve.py --concurrency 1 2 4
    docker compose exec app python src/session02/answer_report_table.py \
        --pattern 'load_serve_*.json' --ttft-p95 500 --total-p95 3000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from metrics import check_slo, comparable  # noqa: E402

REPORTS = ROOT / "reports"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", default="load_*.json")
    ap.add_argument("--ttft-p95", type=float, default=500.0)
    ap.add_argument("--total-p95", type=float, default=3000.0)
    args = ap.parse_args()

    paths = sorted(REPORTS.glob(args.pattern))
    if not paths:
        print(f"レポートが見つかりません: reports/{args.pattern}")
        print("先に `python tools/bench_serve.py --concurrency 1 2 4` を実行してください。")
        return 1

    reports = [json.loads(p.read_text(encoding="utf-8")) for p in paths]

    print("| 条件名 | 件数 | 並列 | TTFT p50 | TTFT p95 | 総時間 p50 | TPOT p50 | スループット | エラー |")
    print("| :--- | --: | --: | --: | --: | --: | --: | --: | --: |")
    for r in reports:
        print(f"| {r['label']} | {r['n']} | {r['concurrency']} | "
              f"{r['ttft']['p50']:.0f} ms | {r['ttft']['p95']:.0f} ms | "
              f"{r['total']['p50']:.0f} ms | {r['tpot']['p50']:.1f} ms | "
              f"{r['throughput_tps']:.1f} tok/s | {r['errors']} |")

    base = reports[0]["conditions"]
    print("\n測定条件")
    for key, value in base.items():
        print(f"  {key:<12}= {value}")
    mismatched = {r["label"]: comparable(base, r["conditions"]) for r in reports[1:]}
    for label, keys in mismatched.items():
        if keys:
            print(f"  ! {label} は条件が違います（同じ表に並べてはいけません）: {keys}")

    slo = {"ttft.p95": args.ttft_p95, "total.p95": args.total_p95}
    print(f"\nSLO 判定（ttft.p95 <= {args.ttft_p95:.0f}ms / total.p95 <= {args.total_p95:.0f}ms）")
    for r in reports:
        violations = check_slo(r, slo)
        verdict = "合格" if not violations else f"違反 -> {violations}"
        print(f"  {r['label']:<12}: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
