#!/usr/bin/env python3
"""intra_op と inter_op を組み合わせて、どちらが効くのかを見る（セッション13 演習）。

  python src/session13/thread_matrix.py
  python src/session13/thread_matrix.py --repeats 100

見たいのは2つ。

  ① inter_op は ORT_SEQUENTIAL では効かない（値を変えても表がほぼ動かない）
  ② intra_op を増やしても、コア数を超えると速くならない

本章のモデルは MatMul -> Add -> Relu … と1本につながった鎖なので、
**同時に走らせられる演算子がそもそも無い**。inter_op が効かないのはそのためである。
分岐のあるモデル（2つの枝を合流させる構造）でなければ、inter_op を上げる意味はない。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_knobs import (  # noqa: E402
    Knobs, build_session, cpu_count, env_line, fixed_input, measure, model_pair,
    size_mb,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=50)
    ap.add_argument("--model", choices=["int8", "fp32"], default="int8")
    args = ap.parse_args()

    fp32, int8 = model_pair()
    target = int8 if args.model == "int8" else fp32
    feeds = fixed_input()

    # 動かす変数は1行につき1つだけ。基準行（1行目）から何を変えたかを列に持つ
    conditions = [
        ("基準", Knobs(intra=1, inter=1)),
        ("intra を 2", Knobs(intra=2, inter=1)),
        ("intra を 4", Knobs(intra=4, inter=1)),
        ("inter を 4（逐次のまま）", Knobs(intra=1, inter=4)),
        ("inter を 4 ＋ 並列モード", Knobs(intra=1, inter=4, parallel=True)),
        ("intra 2 ＋ inter 2 ＋ 並列", Knobs(intra=2, inter=2, parallel=True)),
    ]

    print(f"測定条件: {env_line(args.repeats)}")
    print(f"対象: {args.model}（{size_mb(target):.2f} MB）／CPU {cpu_count()} コア")
    print("\n| 変えたところ | intra | inter | 実行モード | 定常 p50 | 基準比 |")
    print("| :--- | --: | --: | :--- | --: | --: |")
    base = None
    for label, knobs in conditions:
        p50 = measure(build_session(target, knobs), feeds, repeats=args.repeats)["p50"]
        base = p50 if base is None else base
        mode = "parallel" if knobs.parallel else "sequential"
        print(f"| {label} | {knobs.intra} | {knobs.inter} | {mode} | "
              f"{p50:.2f} ms | {p50 / base:.2f} |")

    print("\n読み取り方")
    print("・4 行目（inter を 4・逐次）が基準とほぼ同じなら、"
          "**inter_op は逐次モードでは効いていない**")
    print("・intra の行が下に行くほど遅くなるなら、"
          "**分割と同期のコストが計算の削減を上回っている**")
    print("・どの行が最速かは環境で変わります。この表はあなたの端末の答えです")


if __name__ == "__main__":
    main()
