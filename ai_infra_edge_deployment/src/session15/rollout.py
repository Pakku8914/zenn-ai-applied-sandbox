#!/usr/bin/env python3
"""1,000 台に配るときの数字（セッション15）。

    python src/session15/rollout.py

ここに出る数値は ②物理計算 と ③前提値 だけである（実測ではない）。
もとになるサイズだけが ①実測（セッション12）で、測定条件は本文に併記してある。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fleet import (CLIENT_TIMEOUT_S, DELTA_RATIO, DEVICE_COUNT, FP32_MB, INT8_MB,
                   LINE_MBPS, OBSERVE_HOURS, max_parallel_for_timeout,
                   per_device_seconds, plan_elapsed_hours, stage_plan,
                   total_gb, transfer_seconds, waves)  # noqa: E402


def main() -> int:
    print(f"=== {DEVICE_COUNT:,} 台に配るときの数字 ===")
    print(f"③前提値: 端末 {DEVICE_COUNT:,} 台 / 配布回線 {LINE_MBPS:.1f} Mbps を専有 / "
          f"端末のタイムアウト {CLIENT_TIMEOUT_S:.0f} 秒")
    print(f"①実測  : ONNX fp32 {FP32_MB} MB / int8 {INT8_MB} MB"
          "（2026-08-15 実測・セッション12）")

    print("\n[1] 一斉に配ったときの総量と時間（②物理計算）")
    print(f"| 形式 | 1台 | {DEVICE_COUNT:,} 台の総量 | 回線を専有したときの時間 |")
    print("| :--- | --: | --: | --: |")
    for label, size_mb in (("fp32", FP32_MB), ("int8", INT8_MB)):
        seconds = transfer_seconds(size_mb)
        print(f"| {label} | {size_mb} MB | {total_gb(size_mb):.1f} GB | "
              f"{seconds:,.1f} 秒（{seconds / 60:.1f} 分） |")
    ratio = transfer_seconds(FP32_MB) / transfer_seconds(INT8_MB)
    print(f"int8 にすると配布時間も {ratio:.1f} 分の1 になる（サイズの比がそのまま出る）")

    print(f"\n[2] 同時に何台まで走らせるか（タイムアウト {CLIENT_TIMEOUT_S:.0f} 秒を守る上限）")
    all_at_once = per_device_seconds(INT8_MB, DEVICE_COUNT)
    print(f"同時 {DEVICE_COUNT:>5,} 台: 1台あたり {all_at_once:,.1f} 秒 -> "
          f"タイムアウト {CLIENT_TIMEOUT_S:.0f} 秒を超える")
    limit = max_parallel_for_timeout(INT8_MB)
    print(f"同時 {limit:>5,} 台: 1台あたり {per_device_seconds(INT8_MB, limit):,.1f} 秒 -> "
          "ぎりぎり収まる（上限）")
    parallel = 50
    one = per_device_seconds(INT8_MB, parallel)
    print(f"同時 {parallel:>5,} 台: 1台あたり {one:,.1f} 秒 / "
          f"{waves(DEVICE_COUNT, parallel)} 波 / "
          f"全体 {waves(DEVICE_COUNT, parallel) * one:,.1f} 秒")
    print("波に分けても全体の時間は変わらない。変わるのは1台の待ち時間と失敗の数である。")

    stages = stage_plan()
    print(f"\n[3] 段階展開の計画（③前提値: 各段の観察 {OBSERVE_HOURS:.1f} 時間）")
    print("| 段 | 割合 | この段の台数 | 累積 | 配布 | 観察 |")
    print("| :--- | :--- | --: | --: | --: | --: |")
    for stage in stages:
        print(f"| {stage.index} | {stage.fraction:.1%} | {stage.added:,} | "
              f"{stage.target:,} | {stage.seconds:,.1f} 秒 | "
              f"{stage.observe_hours:.1f} 時間 |")
    total_seconds = sum(stage.seconds for stage in stages)
    print(f"配布の合計 {total_seconds:,.1f} 秒（{total_seconds / 60:.1f} 分）／"
          f"観察を含めた所要 {plan_elapsed_hours(stages):.1f} 時間")
    print("段階展開は帯域を減らさない。減らすのは「間違った版が届く台数」である。")

    full = transfer_seconds(INT8_MB)
    delta = transfer_seconds(INT8_MB * DELTA_RATIO)
    print(f"\n[4] 差分配信にしたら（③前提値: 差分が全体の {DELTA_RATIO:.1%}）")
    print(f"全体配信 {full:,.1f} 秒 -> 差分配信 {delta:,.1f} 秒（節約 {full - delta:,.1f} 秒）")
    print("ただし「どの版からの差分か」で配布物が増える（版の組み合わせの数だけ作る）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
