#!/usr/bin/env python3
"""メモリのつまみとグラフ最適化レベルを比べる（セッション13）。

  python src/session13/arena_probe.py
  python src/session13/arena_probe.py --model fp32 --repeats 100

比べる条件は5つ（動かすのは毎回1つだけ）。

  default      : アリーナ on / メモリパターン on / 最適化 all（既定）
  arena-off    : 確保したメモリを使い回さない
  pattern-off  : 中間バッファの計画を立てない
  opt-disable  : グラフ最適化をしない
  opt-basic    : 基本的な最適化だけ

**条件ごとに別プロセスで測る。** RSS（実メモリ）は解放しても下がらないことが
あるため、同じプロセスで5条件を回すと差が見えない。プロセスを分けて
「そのプロセスが到達した最大の RSS（VmHWM）」を比べるのが素直な測り方である。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))

from runtime_knobs import (  # noqa: E402
    REPORTS, SANDBOX, Knobs, build_session, env_line, fixed_input, measure,
    model_pair, peak_rss_mb, run_once, size_mb,
)

# 子プロセスに渡す名前は ASCII にしておく（環境のロケールに左右されないため）
CONDITIONS: dict[str, tuple[str, Knobs]] = {
    "default": ("既定", Knobs(intra=1)),
    "arena-off": ("アリーナ off", Knobs(intra=1, arena=False)),
    "pattern-off": ("パターン off", Knobs(intra=1, mem_pattern=False)),
    "opt-disable": ("最適化 disable", Knobs(intra=1, opt="disable")),
    "opt-basic": ("最適化 basic", Knobs(intra=1, opt="basic")),
}


def measure_one(name: str, model_kind: str, repeats: int) -> dict:
    """子プロセス側の処理。1条件だけ測って JSON を1行で吐く（ASCII のみ）。"""
    _, knobs = CONDITIONS[name]
    fp32, int8 = model_pair()
    target = int8 if model_kind == "int8" else fp32
    feeds = fixed_input()
    session = build_session(target, knobs)
    probs = run_once(session, feeds)
    got = measure(session, feeds, repeats=repeats)
    return {"name": name, "knobs": knobs.as_dict(),
            "p50": round(got["p50"], 3), "p95": round(got["p95"], 3),
            "peak_rss_mb": peak_rss_mb(),
            "probs": [round(float(v), 6) for v in probs.reshape(-1)]}


def run_child(name: str, model_kind: str, repeats: int) -> dict:
    """条件ごとに別プロセスを起こす。失敗したら子の stderr をそのまま見せる。"""
    proc = subprocess.run(
        [sys.executable, str(HERE), "--one", name, "--model", model_kind,
         "--repeats", str(repeats)],
        capture_output=True, text=True, encoding="utf-8", check=False)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"条件 {name} の測定に失敗しました")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["int8", "fp32"], default="int8")
    ap.add_argument("--repeats", type=int, default=50)
    ap.add_argument("--one", choices=list(CONDITIONS), default=None,
                    help="内部用：この条件だけを測って JSON を出す")
    args = ap.parse_args()

    if args.one:
        print(json.dumps(measure_one(args.one, args.model, args.repeats)))
        return

    fp32, int8 = model_pair()
    target = int8 if args.model == "int8" else fp32
    print(f"測定条件: {env_line(args.repeats)}")
    print(f"対象: {args.model}（{size_mb(target):.2f} MB）／条件ごとに別プロセスで測定")

    results = [run_child(name, args.model, args.repeats) for name in CONDITIONS]
    base = results[0]
    base_probs = np.array(base["probs"], dtype=np.float64)

    print("\n=== つまみを1つずつ動かす ===")
    print("| 条件 | 定常 p50 | 既定比 | 最大 RSS | 既定との出力の最大差 |")
    print("| :--- | --: | --: | --: | --: |")
    for row in results:
        diff = float(np.abs(np.array(row["probs"], dtype=np.float64) - base_probs).max())
        row["max_prob_diff_vs_default"] = diff
        rss = row["peak_rss_mb"]
        print(f"| {CONDITIONS[row['name']][0]} | {row['p50']:.2f} ms | "
              f"{row['p50'] / max(base['p50'], 1e-9):.2f} | "
              f"{f'{rss:.1f} MB' if rss is not None else '—'} | {diff:.2e} |")

    worst = max(r["max_prob_diff_vs_default"] for r in results)
    print(f"\n出力の最大差（全条件）: {worst:.2e}")
    print("-> つまみは**速度とメモリを変えるが、答えは変えない**。"
          "答えが変わったら、それはつまみではなくモデルか前処理の問題です。")
    print("-> RSS には重み・中間バッファ・ランタイム本体・Python 自体が全部入ります。"
          "セッション11の「重み＋実行時＋アプリ」のうち、実行時のぶんがここに出ます。")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "bench_edge_arena.json"
    out.write_text(json.dumps(
        {"env": env_line(args.repeats), "model": args.model,
         "model_mb": round(size_mb(target), 2),
         "rows": [{k: v for k, v in r.items() if k != "probs"} for r in results]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out.relative_to(SANDBOX)}")


if __name__ == "__main__":
    main()
