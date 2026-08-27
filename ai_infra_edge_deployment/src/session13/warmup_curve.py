#!/usr/bin/env python3
"""初回推論と定常時の差を測り、ウォームアップ回数を決める（セッション13）。

  python src/session13/warmup_curve.py
  python src/session13/warmup_curve.py --model fp32 --calls 15 --repeats 100

測るのは2つ。

  ① セッションを作った直後、1回目・2回目・3回目…がどう変わるか
     -> 何回ウォームアップすれば定常になるかが決まる
  ② セッションを毎回作り直すと、1件あたりの時間がどうなるか
     -> 「セッションは使い回す」の根拠になる

②の差はモデルの読み込みとグラフ最適化のぶんである。**起動時に1回払うか、
リクエストごとに払うか**の違いなので、絶対値ではなく向きを見ればよい。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_knobs import (  # noqa: E402
    REPORTS, SANDBOX, Knobs, build_session, env_line, fixed_input, measure,
    model_pair, size_mb,
)

STEADY_TOLERANCE = 1.5   # 定常 p50 の 1.5 倍以内に入ったら「定常に入った」とみなす


def first_calls(model: Path, knobs: Knobs, calls: int) -> list[float]:
    """セッション作成直後から calls 回、1回ずつ時間を測る（ウォームアップなし）。"""
    session = build_session(model, knobs)
    out: list[float] = []
    feeds = fixed_input()
    for _ in range(calls):
        t0 = time.perf_counter()
        session.run(None, feeds)
        out.append((time.perf_counter() - t0) * 1000)
    return out


def per_call_new_session(model: Path, knobs: Knobs, calls: int) -> list[float]:
    """**毎回セッションを作って1回だけ推論する**（やってはいけない書き方の実測）。"""
    out: list[float] = []
    feeds = fixed_input()
    for _ in range(calls):
        t0 = time.perf_counter()
        session = build_session(model, knobs)
        session.run(None, feeds)
        out.append((time.perf_counter() - t0) * 1000)
    return out


def steady_from(curve: list[float], steady_p50: float) -> int:
    """何回目から定常とみなせるか（1 始まり）。最後まで入らなければ 0 を返す。"""
    for i, value in enumerate(curve, start=1):
        if value <= steady_p50 * STEADY_TOLERANCE:
            return i
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["int8", "fp32"], default="int8")
    ap.add_argument("--intra", type=int, default=1)
    ap.add_argument("--calls", type=int, default=10)
    ap.add_argument("--repeats", type=int, default=50)
    args = ap.parse_args()

    fp32, int8 = model_pair()
    target = int8 if args.model == "int8" else fp32
    knobs = Knobs(intra=args.intra)
    feeds = fixed_input()

    print(f"測定条件: {env_line(args.repeats)}")
    print(f"対象: {args.model}（{size_mb(target):.2f} MB）/ {knobs.label()}")

    steady = measure(build_session(target, knobs), feeds, repeats=args.repeats)
    curve = first_calls(target, knobs, args.calls)
    enters = steady_from(curve, steady["p50"])

    print("\n=== 初回推論と定常時 ===")
    print(f"初回     : {curve[0]:.2f} ms")
    print(f"定常 p50 : {steady['p50']:.2f} ms（ウォームアップ 5 回のあと "
          f"{args.repeats} 回の中央値）")
    print(f"比       : {curve[0] / max(steady['p50'], 1e-9):.1f} 倍")
    print(f"定常に入った回: {enters if enters else '未到達'} 回目"
          f"（定常 p50 の {STEADY_TOLERANCE} 倍以内に入った最初の回）")

    print(f"\n=== セッション作成直後の {args.calls} 回（この環境の値）===")
    print("| 回 | レイテンシ | 定常 p50 比 |")
    print("| --: | --: | --: |")
    for i, value in enumerate(curve, start=1):
        print(f"| {i} | {value:.2f} ms | {value / max(steady['p50'], 1e-9):.2f} |")

    print("\n=== セッションを毎回作るか、使い回すか ===")
    each = per_call_new_session(target, knobs, args.calls)
    each_sorted = sorted(each)
    each_p50 = each_sorted[len(each_sorted) // 2]
    print(f"毎回作る（作成＋1回推論）の中央値 : {each_p50:.2f} ms")
    print(f"使い回す（定常 p50）             : {steady['p50']:.2f} ms")
    print(f"倍率                             : "
          f"{each_p50 / max(steady['p50'], 1e-9):.1f} 倍")
    print("-> 差はモデルの読み込みとグラフ最適化のぶんです。"
          "起動時に1回払うべきコストを、リクエストごとに払っているのが「毎回作る」。")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "bench_edge_warmup.json"
    out.write_text(json.dumps(
        {"env": env_line(args.repeats), "model": args.model,
         "model_mb": round(size_mb(target), 2), "knobs": knobs.as_dict(),
         "steady": {k: round(v, 3) for k, v in steady.items()},
         "first_calls_ms": [round(v, 3) for v in curve],
         "steady_from_call": enters,
         "new_session_per_call_p50_ms": round(each_p50, 3)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out.relative_to(SANDBOX)}")


if __name__ == "__main__":
    main()
