#!/usr/bin/env python3
"""バッチ化が効くか効かないかを測る（セッション13）。

  python src/session13/batch_probe.py
  python src/session13/batch_probe.py --batches 1 2 4 8 16 --repeats 30

前章で形状を `[1, 384]` に固定した。端末はリクエストが1件ずつ来るので、
それが普通の形である。では**まとめて処理できるなら得なのか**を測る。

得になる理屈：重みの読み出しは1回で済むので、2件目以降は重みを読み直さない。
得にならない理屈：計算量は件数ぶん増えるので、計算が律速なら素直に比例して伸びる。
どちらが勝つかは**モデルと端末で変わる**。だから測る。

この比較のために、重みをまったく触らずバッチ次元だけ動的にしたコピーを作る。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_knobs import (  # noqa: E402
    REPORTS, SANDBOX, Knobs, build_session, ensure_dynamic_batch, env_line,
    fixed_input, measure, model_pair, peak_rss_mb, run_once, size_mb,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--intra", type=int, default=1)
    ap.add_argument("--repeats", type=int, default=30)
    args = ap.parse_args()

    fp32, _int8 = model_pair()
    dyn = ensure_dynamic_batch(fp32)
    knobs = Knobs(intra=args.intra)

    print(f"測定条件: {env_line(args.repeats)}")
    print(f"固定バッチ : {fp32.name}（{size_mb(fp32):.2f} MB）")
    print(f"動的バッチ : {dyn.name}（{size_mb(dyn):.2f} MB・重みは同じ）")

    # ① 形状を動的にしても答えは同じか（バッチ1で突き合わせる）
    fixed_out = run_once(build_session(fp32, knobs), fixed_input(1))
    dyn_session = build_session(dyn, knobs)
    dyn_out = run_once(dyn_session, fixed_input(1))
    diff = float(np.abs(fixed_out - dyn_out).max())
    print("\n=== 形状を動的にしても答えは変わらないか ===")
    print(f"入力の形状の宣言: {dyn_session.get_inputs()[0].shape}")
    print(f"バッチ1 の出力の最大差: {diff:.2e} -> "
          f"{'同じ（宣言を変えただけ）' if diff < 1e-5 else '違う（作り方を見直す）'}")

    # ② バッチを増やすと、1件あたりの時間はどうなるか
    print("\n=== バッチを増やす（1件あたりで比べる）===")
    print(f"| バッチ | 1回の p50 | 1件あたり | バッチ{args.batches[0]}比（1件あたり） |")
    print("| --: | --: | --: | --: |")
    rows = []
    for batch in args.batches:
        got = measure(dyn_session, fixed_input(batch), repeats=args.repeats)
        per = got["p50"] / batch
        rows.append({"batch": batch, "p50_ms": round(got["p50"], 3),
                     "per_sample_ms": round(per, 4)})
        ratio = per / max(rows[0]["per_sample_ms"], 1e-9)   # 0 除算を避ける
        print(f"| {batch} | {got['p50']:.2f} ms | {per:.3f} ms | {ratio:.2f} |")

    best = min(rows, key=lambda r: r["per_sample_ms"])
    gain = rows[0]["per_sample_ms"] / max(best["per_sample_ms"], 1e-9)
    print(f"\n1件あたりが最も短いバッチ: {best['batch']}（{best['per_sample_ms']:.3f} ms）")
    if best["batch"] == 1:
        print("-> この環境・このモデルでは**バッチ化は効きません**。"
              "1件ずつ回すのが最速です。")
    else:
        print(f"-> この環境・このモデルでは、バッチ {best['batch']} で1件あたりが "
              f"{gain:.2f} 倍短くなります。")
    print("ただしバッチ化は**待つこと**とセットです。1件目は仲間が揃うまで待たされる"
          "ので、1件の応答時間（レイテンシ）は必ず悪化します。")
    rss = peak_rss_mb()
    if rss is not None:
        print(f"最大 RSS: {rss:.1f} MB（バッチを増やすと中間バッファのぶん増えます）")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "bench_edge_batch.json"
    out.write_text(json.dumps(
        {"env": env_line(args.repeats), "model": fp32.name,
         "dynamic_model": dyn.name, "knobs": knobs.as_dict(),
         "batch1_output_max_diff": diff, "rows": rows,
         "best_batch": best["batch"], "peak_rss_mb": rss},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out.relative_to(SANDBOX)}")


if __name__ == "__main__":
    main()
