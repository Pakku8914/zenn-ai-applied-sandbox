#!/usr/bin/env python3
"""スレッド数を振って最適点を探す（セッション13）。

  python src/session13/thread_sweep.py
  python src/session13/thread_sweep.py --intra 1 2 4 8 --repeats 100
  python src/session13/thread_sweep.py --model fp32

**「N が最適」は環境で変わる。** このスクリプトが出すのは「あなたの環境での最適点」
だけである。本にもドキュメントにも、あなたの端末の答えは書いていない。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_knobs import (  # noqa: E402
    REPORTS, SANDBOX, Knobs, build_session, cpu_count, env_line, fixed_input, measure,
    model_pair, size_mb,
)

SCALE_FLOOR_MS = 1.0   # fp32 の定常 p50 がこれ以上あれば、速度差を語ってよい規模


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--intra", type=int, nargs="+", default=[1, 2, 4],
                    help="intra_op_num_threads に入れる値の一覧")
    ap.add_argument("--model", choices=["int8", "fp32"], default="int8")
    ap.add_argument("--repeats", type=int, default=50)
    ap.add_argument("--hidden", type=int, default=4096)
    args = ap.parse_args()

    fp32, int8 = model_pair(args.hidden)
    target = int8 if args.model == "int8" else fp32
    feeds = fixed_input()

    print(f"測定条件: {env_line(args.repeats)}")

    # ① まず「語ってよい規模か」を確かめる（前章の scale_check と同じ判定）
    base = measure(build_session(fp32, Knobs(intra=1)), feeds, repeats=args.repeats)
    verdict = ("1 ms 以上なので、この規模なら速度差を語ってよい"
               if base["p50"] >= SCALE_FLOOR_MS
               else "1 ms 未満。差を語る前に --repeats を増やして分布を見ること")
    print("\n=== 規模の確認（fp32・intra_op=1）===")
    print(f"fp32 の定常 p50 : {base['p50']:.2f} ms -> {verdict}")

    # ② スレッド数だけを動かす（変数は1つずつ）
    print(f"\n=== スレッド数を振る（{args.model} / {size_mb(target):.2f} MB "
          f"/ intra_op を変える）===")
    print(f"| intra_op | 定常 p50 | intra_op={args.intra[0]} 比 |")
    print("| --: | --: | --: |")
    rows = []
    for intra in args.intra:
        knobs = Knobs(intra=intra)
        got = measure(build_session(target, knobs), feeds, repeats=args.repeats)
        rows.append({"intra": intra, **{k: round(v, 3) for k, v in got.items()}})
        head = max(rows[0]["p50"], 1e-9)     # 極端に小さいモデルでの 0 除算を避ける
        print(f"| {intra} | {got['p50']:.2f} ms | {got['p50'] / head:.2f} |")

    fastest = min(rows, key=lambda r: r["p50"])
    slowest = max(rows, key=lambda r: r["p50"])
    print(f"\n最速: intra_op={fastest['intra']}（{fastest['p50']:.2f} ms）"
          f"／最遅: intra_op={slowest['intra']}（{slowest['p50']:.2f} ms）")
    print(f"この環境の CPU は {cpu_count()} コアです。"
          "最速のスレッド数は環境で変わります。")
    print("**あなたの環境の答えは、あなたが測った表にしかありません。**")
    if fastest["intra"] != max(args.intra):
        print("-> 最大のスレッド数が最速ではありませんでした。"
              "「増やせば速い」が成り立たない実例です。")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "bench_edge_threads.json"
    out.write_text(json.dumps(
        {"env": env_line(args.repeats), "cpu_count": cpu_count(),
         "model": args.model, "model_mb": round(size_mb(target), 2),
         "repeats": args.repeats, "scale_check_fp32_p50_ms": round(base["p50"], 3),
         "rows": rows, "fastest_intra": fastest["intra"]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out.relative_to(SANDBOX)}（p95・min も入っています）")


if __name__ == "__main__":
    main()
