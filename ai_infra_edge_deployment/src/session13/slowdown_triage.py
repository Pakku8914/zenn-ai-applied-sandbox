#!/usr/bin/env python3
"""「速くならない」を4人の容疑者に分解して順に調べる（セッション13）。

  python src/session13/slowdown_triage.py
  python src/session13/slowdown_triage.py --repeats 100

容疑者は次の4人。**上から順に、確認が軽い順**に並べてある。

  ① そもそも測れる規模か（ノイズの床に埋もれていないか）
  ② ウォームアップしているか（初回推論を定常値として扱っていないか）
  ③ スレッドが多すぎないか（増やせば速いは成り立たない）
  ④ セッションを毎回作っていないか（読み込みと最適化を毎回払っていないか）

①②はあなたの**測り方**の問題、③④はあなたの**設定と実装**の問題である。
順番を守ること。①を飛ばして③④をいじると、ノイズを追いかけて一日が終わる。
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
    measure, model_pair, size_mb,
)

FLOOR_MS = 1.0
NOISE_MS = 0.5


def suspect_scale(fp32: Path, repeats: int) -> dict:
    got = measure(build_session(fp32, Knobs(intra=1)), fixed_input(), repeats=repeats)
    p50 = got["p50"]
    if p50 >= FLOOR_MS:
        return {"ok": True, "value": f"fp32 の定常 p50 = {p50:.2f} ms",
                "note": "1 ms 以上ある。速度の議論をしてよい規模",
                "next": "次の容疑者へ"}
    if p50 >= NOISE_MS:
        return {"ok": False, "value": f"fp32 の定常 p50 = {p50:.2f} ms",
                "note": "境界。実行ごとの揺れが結論を左右する",
                "next": "--repeats を増やし、複数回の実行で再現するか見る"}
    return {"ok": False, "value": f"fp32 の定常 p50 = {p50:.2f} ms",
            "note": "ノイズの床に埋もれている。この規模で「N 倍速い」は言えない",
            "next": "モデルを大きくする／測る単位を1推論ではなく1000推論にする"}


def suspect_warmup(target: Path, repeats: int) -> dict:
    session = build_session(target, Knobs(intra=1))
    feeds = fixed_input()
    t0 = time.perf_counter()
    session.run(None, feeds)
    first = (time.perf_counter() - t0) * 1000
    steady = measure(session, feeds, repeats=repeats)["p50"]
    ratio = first / max(steady, 1e-9)
    return {"ok": True,
            "value": f"初回 {first:.2f} ms / 定常 p50 {steady:.2f} ms（{ratio:.1f} 倍）",
            "note": "初回にはグラフの最適化とメモリ確保が入る。"
                    "この倍率は実行ごとに揺れる",
            "next": "報告では初回と定常を**別の行**に分ける。"
                    "混ぜて平均した数字は使わない"}


def suspect_threads(target: Path, repeats: int) -> dict:
    cores = cpu_count()
    candidates = sorted({1, cores, cores * 2, 4})
    rows = []
    for intra in candidates:
        got = measure(build_session(target, Knobs(intra=intra)), fixed_input(),
                      repeats=repeats)
        rows.append((intra, got["p50"]))
    best = min(rows, key=lambda r: r[1])
    worst = max(rows, key=lambda r: r[1])
    table = " / ".join(f"{intra}:{p50:.2f}ms" for intra, p50 in rows)
    too_many = best[0] != max(candidates)
    return {"ok": True, "too_many_threads_is_slower": too_many,
            "value": f"{table}（最速 intra_op={best[0]}）",
            "note": (f"最大の {max(candidates)} スレッドは最速ではない"
                     f"（最遅は intra_op={worst[0]}）" if too_many
                     else "この環境では最大のスレッド数が最速だった"),
            "next": f"intra_op={best[0]} を設定表に書き、"
                    "端末が変わったらもう一度この表を作る"}


def suspect_session(target: Path, repeats: int) -> dict:
    knobs = Knobs(intra=1)
    feeds = fixed_input()
    steady = measure(build_session(target, knobs), feeds, repeats=repeats)["p50"]
    each = []
    for _ in range(5):
        t0 = time.perf_counter()
        build_session(target, knobs).run(None, feeds)
        each.append((time.perf_counter() - t0) * 1000)
    each.sort()
    per_call = each[len(each) // 2]
    return {"ok": True,
            "value": f"毎回作る {per_call:.2f} ms / 使い回す {steady:.2f} ms"
                     f"（{per_call / max(steady, 1e-9):.1f} 倍）",
            "note": "差はモデルの読み込みとグラフ最適化。"
                    "リクエストごとに払うものではない",
            "next": "セッションはプロセス起動時に1つ作り、以後は使い回す"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["int8", "fp32"], default="int8")
    ap.add_argument("--repeats", type=int, default=50)
    args = ap.parse_args()

    fp32, int8 = model_pair()
    target = int8 if args.model == "int8" else fp32
    print(f"測定条件: {env_line(args.repeats)}")
    print(f"対象: {args.model}（{size_mb(target):.2f} MB）")

    checks = [
        ("① 測れる規模か", suspect_scale(fp32, args.repeats)),
        ("② ウォームアップしているか", suspect_warmup(target, args.repeats)),
        ("③ スレッドが多すぎないか", suspect_threads(target, args.repeats)),
        ("④ セッションを毎回作っていないか", suspect_session(target, args.repeats)),
    ]

    print("\n=== 「速くならない」の切り分け ===")
    for label, result in checks:
        print(f"\n{label}")
        print(f"    測った値 : {result['value']}")
        print(f"    所見     : {result['note']}")
        print(f"    次の一手 : {result['next']}")

    print("\nここまで潰しても速くならない場合、残るのは"
          "**モデルの構造**（前章の「追加ノードのコストが削減分を上回る」）と"
          "**端末そのものの上限**です。つまみで解ける範囲は、ここで終わりです。")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "bench_edge_triage.json"
    out.write_text(json.dumps(
        {"env": env_line(args.repeats), "model": args.model,
         "checks": [{"label": label, **result} for label, result in checks]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out.relative_to(SANDBOX)}")


if __name__ == "__main__":
    main()
