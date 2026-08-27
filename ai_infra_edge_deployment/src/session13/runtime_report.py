#!/usr/bin/env python3
"""端末ごとの「ランタイム設定表」を作る（セッション13の引き継げる成果物）。

  python src/session13/runtime_report.py --device 端末A --intra 2
  python src/session13/runtime_report.py --device 端末D --intra 1 --model int8 \
      --reason "メモリ上限 512MB のため int8 固定。スレッドは1で足りた"

出すのは2つ。

  reports/edge_runtime_settings.md   人が読む設定表（そのまま引き継げる）
  reports/bench_edge_runtime.json    機械が読む記録（次回との差分を取る）

**測定は3回行って中央値を採る**（本書の測定規約）。1回の測定で設定を決めない。
設定表に測定条件が書いていなければ、その表は次の担当者には使えない。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_knobs import (  # noqa: E402
    REPORTS, SANDBOX, Knobs, build_session, cpu_count, env_line, fixed_input,
    measure_median_of_runs, model_pair, peak_rss_mb, size_mb,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="端末A", help="セッション11で定義した端末名")
    ap.add_argument("--model", choices=["int8", "fp32"], default="int8")
    ap.add_argument("--intra", type=int, default=1)
    ap.add_argument("--inter", type=int, default=1)
    ap.add_argument("--parallel", action="store_true")
    ap.add_argument("--no-arena", action="store_true")
    ap.add_argument("--opt", default="all")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--repeats", type=int, default=50)
    ap.add_argument("--reason", default="（この設定にした理由を書いてください）")
    args = ap.parse_args()

    fp32, int8 = model_pair()
    target = int8 if args.model == "int8" else fp32
    knobs = Knobs(intra=args.intra, inter=args.inter, parallel=args.parallel,
                  arena=not args.no_arena, opt=args.opt)
    feeds = fixed_input()

    session = build_session(target, knobs)
    t0 = time.perf_counter()
    session.run(None, feeds)
    first_ms = (time.perf_counter() - t0) * 1000
    got = measure_median_of_runs(session, feeds, runs=args.runs, repeats=args.repeats)
    rss = peak_rss_mb()

    lines = [
        f"## ランタイム設定表：{args.device}（{args.model}）",
        "",
        "| 項目 | 値 |",
        "| :--- | :--- |",
        f"| 端末 | {args.device}（前提値はセッション11の表） |",
        f"| モデル | `{target.name}`（{size_mb(target):.2f} MB） |",
        f"| intra_op | {knobs.intra} |",
        f"| inter_op | {knobs.inter}"
        f"（{'ORT_PARALLEL' if knobs.parallel else 'ORT_SEQUENTIAL なので効かない'}） |",
        f"| メモリアリーナ | {'有効' if knobs.arena else '無効'} |",
        f"| メモリパターン | {'有効' if knobs.mem_pattern else '無効'} |",
        f"| グラフ最適化 | {knobs.opt} |",
        f"| 実行プロバイダ | {session.get_providers()} |",
        f"| 初回推論 | {first_ms:.2f} ms |",
        f"| 定常 p50 | {got['p50']:.2f} ms |",
        f"| 定常 p95 | {got['p95']:.2f} ms |",
        f"| 最大 RSS | {f'{rss:.1f} MB' if rss is not None else '取得できない環境'} |",
        f"| 測定条件 | {env_line(args.repeats)}／{args.runs} 回測って中央値 |",
        f"| この設定にした理由 | {args.reason} |",
        "",
        "> 絶対値は環境で変わります。**次回この表を作り直すときは、"
        "同じ入力・同じ回数・同じ端末で測ってください。**条件が変われば比較できません。",
    ]
    report = "\n".join(lines)
    print(report)

    REPORTS.mkdir(parents=True, exist_ok=True)
    md = REPORTS / "edge_runtime_settings.md"
    md.write_text(report + "\n", encoding="utf-8")
    js = REPORTS / "bench_edge_runtime.json"
    js.write_text(json.dumps(
        {"device": args.device, "model": args.model, "model_mb": round(size_mb(target), 2),
         "knobs": knobs.as_dict(), "providers": session.get_providers(),
         "cpu_count": cpu_count(), "runs": args.runs, "repeats": args.repeats,
         "first_ms": round(first_ms, 3),
         "steady": {k: round(v, 3) for k, v in got.items()},
         "peak_rss_mb": rss, "env": env_line(args.repeats), "reason": args.reason},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {md.relative_to(SANDBOX)}")
    print(f"-> {js.relative_to(SANDBOX)}")


if __name__ == "__main__":
    main()
