#!/usr/bin/env python3
"""手元にない端末群の何を見るか（セッション15）。

    python src/session15/fleet_report.py

**この端末群は決定的に作った架空のデータである。** 本書は実端末群を持っていないので、
OTA（無線経由の更新）の成功率や実際の配信時間の実測値はどこにも無い。ここで学ぶのは
「どの指標を、どの形で受け取り、どの閾値で判断するか」の設計である。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fleet import (AGG_BYTES_PER_DAY, BUCKET_LABELS, DEVICE_COUNT,
                   DEVICE_PAYLOAD_KEYS, EQ_MARGIN, EQ_MAX_DIFF, EQ_MAX_DIFF_LIMIT,
                   FAILURE_TOLERANCE, GB, MB, OBSERVE_HOURS,
                   RAW_BYTES_PER_SAMPLE, SAMPLES_PER_DAY, TELEMETRY_DAYS,
                   fleet_totals, merge_buckets, quantile_bucket, release_gate,
                   rollout_gate, sample_fleet, telemetry_bytes,
                   version_mix)  # noqa: E402


def main() -> int:
    fleet = sample_fleet()
    stats = version_mix(fleet)
    totals = fleet_totals(fleet)
    new, current = stats[0], stats[1]

    print(f"=== 手元にない {DEVICE_COUNT:,} 台の何を見るか ===")
    print("この端末群は決定的に作った架空のデータです（本書は実端末群を持っていません）")

    print(f"\n[1] モデルの版別の分布（観察窓 {OBSERVE_HOURS:.1f} 時間 / "
          f"オフライン判定 {OBSERVE_HOURS:.1f} 時間）")
    print("| 版 | 台数 | 割合 | 推論 | 失敗 | 失敗率 | オフライン |")
    print("| :--- | --: | --: | --: | --: | --: | --: |")
    for stat in stats:
        print(f"| {stat.version} | {stat.devices:,} | {stat.ratio:.1%} | "
              f"{stat.inferences:,} | {stat.failures:,} | "
              f"{stat.failure_rate:.3%} | {stat.offline:,} |")
    print(f"全体: {totals.devices:,} 台 / {totals.inferences:,} 件 / "
          f"失敗 {totals.failures:,} 件（{totals.failure_rate:.3%}）/ "
          f"オフライン {totals.offline:,} 台（{totals.offline_ratio:.1%}）")

    all_buckets = merge_buckets(fleet)
    print("\n[2] レイテンシは「足せる形」で受け取る（バケットの件数）")
    print(f"| 区間 | 全体 | {new.version} | {current.version} |")
    print("| :--- | --: | --: | --: |")
    for index, label in enumerate(BUCKET_LABELS):
        print(f"| {label} | {all_buckets[index]:,} | {new.buckets[index]:,} | "
              f"{current.buckets[index]:,} |")
    print(f"p50: 全体は {quantile_bucket(all_buckets, 0.50)}")
    print(f"p95: {new.version} は {quantile_bucket(new.buckets, 0.95)} / "
          f"{current.version} は {quantile_bucket(current.buckets, 0.95)} -> 新版のほうが悪い")

    gate = release_gate(EQ_MAX_DIFF, clear_agree=True)
    print("\n[3] 配る前の門（セッション12 の等価性・①実測）")
    print(f"確率の最大差 {EQ_MAX_DIFF:.6f} <= {EQ_MAX_DIFF_LIMIT:.6f} -> "
          f"{'通過' if EQ_MAX_DIFF <= EQ_MAX_DIFF_LIMIT else '不通過'}")
    print(f"マージン {EQ_MARGIN:.2f} 以上のサンプルは全件一致 -> 通過")
    print(f"判定: {gate.verdict}")

    decision = rollout_gate(new, current)
    print(f"\n[4] 配った後の門（新版 {new.version} を現行 {current.version} と比べる）")
    print(f"新版の失敗率 {new.failure_rate:.3%} / 現行 {current.failure_rate:.3%} / "
          f"許容 {current.failure_rate * FAILURE_TOLERANCE:.3%}"
          f"（現行の {FAILURE_TOLERANCE} 倍・③前提値）")
    print(f"判定: {decision.verdict} — {decision.reasons[0]}")
    print(f"更新の成功率だけ見ると {new.devices}/{new.devices} 台 = "
          f"{1.0:.1%} で「成功」に見える")

    print("\n[5] 端末から送るもの・送らないもの")
    print("送る  : " + ", ".join(DEVICE_PAYLOAD_KEYS))
    print("送らない: 入力データ / 出力の生の値 / 自由文 / 位置情報 / 個人を特定できる識別子")
    raw_day = RAW_BYTES_PER_SAMPLE * SAMPLES_PER_DAY
    print(f"1台1日の転送量（③前提値）: 生データ {raw_day:,} バイト -> "
          f"集約 {AGG_BYTES_PER_DAY:,} バイト（{raw_day // AGG_BYTES_PER_DAY:,} 分の1）")
    print(f"{DEVICE_COUNT:,} 台・{TELEMETRY_DAYS} 日: "
          f"生データ {telemetry_bytes(raw=True) / GB:.2f} GB -> "
          f"集約 {telemetry_bytes() / MB:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
