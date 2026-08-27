#!/usr/bin/env python3
"""エッジに出す割合を振って、クラウド側とエッジ側を1つの表にする（復習3）。

    python src/review03/handoff_sweep.py
    python src/review03/handoff_sweep.py --device A --peak-rps 2.0
    python src/review03/handoff_sweep.py --memo

この章の背骨（受け渡しの鎖）をそのまま関数にしたものである。

  セッション4・9   : 飽和点を避けて選んだ動作点の rps（①実測）
  セッション9      : ヘッドルームを引いた1本の能力と、必要レプリカ数（下限つき）
  セッション10     : 1000リクエスト単価（相対単位。特定クラウドの価格は書かない）
  セッション3・11  : エッジに置くモデルのフットプリント（重み ＋ KVキャッシュ ＋ 実行時）
  セッション12     : エッジに置くのは int8 の分類器（サイズは①実測）

**絶対値は再現しない。** レイテンシは実行ごとに2倍程度ぶれる。ここで学ぶのは
「エッジに逃がすと上流の rps は下がるが、1000リクエスト単価は下がるとは限らない」
という関係である。
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session09.scaling import (  # noqa: E402
    MEASURED_CONDITIONS, SLOTS_PER_INSTANCE, Slo, best_point,
)
from src.session11.edge_budget import (  # noqa: E402
    Footprint, MemoryBudget, fits, kv_mb,
)

# --- ③ 前提値（読者が自分の環境の値に置き換える）---------------------------
DEVICES: dict[str, MemoryBudget] = {
    "A": MemoryBudget(total_mb=4096, os_reserved_mb=1024, other_apps_mb=1536),
    "B": MemoryBudget(total_mb=2048, os_reserved_mb=768, other_apps_mb=512),
    "C": MemoryBudget(total_mb=8192, os_reserved_mb=1024, other_apps_mb=1024),
    "D": MemoryBudget(total_mb=1024, os_reserved_mb=256, other_apps_mb=128),
}
RUNTIME_MB = 150.0            # 言語モデルの実行時の作業メモリ
CLASSIFIER_RUNTIME_MB = 50.0  # 分類器だけを動かす場合の実行時メモリ
SEQ_LEN = 2048                # 想定する系列長
HEADROOM = 0.30               # セッション9 で空けたヘッドルーム
FLOOR = 2                     # minReplicas の下限（0 にしない）

# --- ① 実測値（2026-08-15 実測。測定条件は MEASURED_CONDITIONS）------------
Q4_K_M_MB = 379.4     # models/gguf/qwen05b-q4_k_m.gguf
ONNX_INT8_MB = 17.56  # models/onnx/int8 の分類器


def upstream_rps(peak_rps: float, edge_ratio: float) -> float:
    """エッジで解決した分を引いて、上流に届く rps を出す。"""
    if peak_rps <= 0:
        raise ValueError("peak_rps は正の数を指定してください")
    if not 0.0 <= edge_ratio <= 1.0:
        raise ValueError("edge_ratio は 0.0 以上 1.0 以下で指定してください")
    return peak_rps * (1.0 - edge_ratio)


def per_instance_rps(point_rps: float, headroom: float = HEADROOM) -> float:
    """1本に安全に任せられる rps（ヘッドルームを引いた値）。"""
    if point_rps <= 0:
        raise ValueError("point_rps は正の数を指定してください")
    if not 0.0 <= headroom < 1.0:
        raise ValueError("headroom は 0 以上 1 未満で指定してください")
    return point_rps * (1.0 - headroom)


def replicas_for(served_rps: float, capacity_rps: float,
                 floor: int = FLOOR) -> int:
    """必要レプリカ数。**切り上げと下限が入るので需要に比例して減らない。**"""
    if capacity_rps <= 0:
        raise ValueError("capacity_rps は正の数を指定してください")
    if floor < 1:
        raise ValueError("floor は 1 以上を指定してください（0 にしない）")
    return max(floor, math.ceil(served_rps / capacity_rps))


def cost_per_1k(replicas: int, served_rps: float, hourly: float = 1.0) -> float:
    """1000リクエスト単価（相対単位）。分母は**実際に処理した件数**である。"""
    if served_rps <= 0:
        return math.inf   # 上流に届かない。単価は定義できない（0 で割らない）
    return hourly * replicas / (served_rps * 3600.0) * 1000.0


def utilization(served_rps: float, replicas: int, point_rps: float) -> float:
    """実際に埋まっている割合。台数が減らないとここが落ちる。"""
    if replicas < 1 or point_rps <= 0:
        raise ValueError("replicas は 1 以上、point_rps は正の数です")
    return served_rps / (point_rps * replicas)


def generation_footprint(seq_len: int = SEQ_LEN) -> Footprint:
    """0.5B級 Q4_K_M で回答を生成する場合（重み ＋ KVキャッシュ ＋ 実行時）。"""
    return Footprint(weights_mb=Q4_K_M_MB, kv_mb=kv_mb("qwen05b", seq_len),
                     runtime_mb=RUNTIME_MB)


def classifier_footprint(count: int = 2) -> Footprint:
    """int8 の分類器を count 本置く場合。**KVキャッシュは足さない**（系列を持たない）。"""
    if count < 0:
        raise ValueError("count は 0 以上を指定してください")
    if count == 0:
        return Footprint(weights_mb=0.0, kv_mb=0.0, runtime_mb=0.0)
    return Footprint(weights_mb=ONNX_INT8_MB * count, kv_mb=0.0,
                     runtime_mb=CLASSIFIER_RUNTIME_MB)


@dataclass(frozen=True)
class Case:
    """エッジで解決する割合を1つ決めたときの、クラウド側とエッジ側の姿。"""

    edge_ratio: float
    served_rps: float
    replicas: int
    utilization: float
    cost_per_1k: float
    edge_total_mb: float
    device: str
    device_limit_mb: float
    edge_fits: bool
    slack_mb: float

    @property
    def on_edge(self) -> bool:
        """端末側に何かを置くか（割合 0 なら置かない）。"""
        return self.edge_ratio > 0.0


def sweep(*, peak_rps: float = 5.0,
          ratios: tuple[float, ...] = (0.0, 0.5, 0.8, 0.95),
          device: str = "D", hourly: float = 1.0, headroom: float = HEADROOM,
          floor: int = FLOOR, classifiers: int = 2) -> list[Case]:
    """割合を振ってケースを並べる。**動作点は SLO を満たす最大の点**を使う。"""
    if device not in DEVICES:
        raise ValueError(f"知らない端末です: {device}（A〜D で指定）")
    budget = DEVICES[device]
    # 「rps が最大の点」ではなく「SLO を満たす中で rps が最大の点」を採る
    point = best_point(slo=Slo())
    capacity = per_instance_rps(point.throughput_rps, headroom)
    cases: list[Case] = []
    for ratio in ratios:
        served = upstream_rps(peak_rps, ratio)
        replicas = replicas_for(served, capacity, floor)
        fp = classifier_footprint(classifiers if ratio > 0.0 else 0)
        ok, slack = fits(budget, fp)
        cases.append(Case(
            edge_ratio=ratio, served_rps=served, replicas=replicas,
            utilization=utilization(served, replicas, point.throughput_rps),
            cost_per_1k=cost_per_1k(replicas, served, hourly),
            edge_total_mb=fp.total_mb, device=device,
            device_limit_mb=budget.limit_mb, edge_fits=ok, slack_mb=slack))
    return cases


def table(cases: list[Case]) -> str:
    """Markdown の表。**単価が定義できない行は数字を作らない。**"""
    lines = ["| エッジで解決する割合 | 上流に届く rps | レプリカ数 | 利用率 "
             "| 1000リクエスト単価 | エッジ側のフットプリント | 端末に載るか | 余白 |",
             "| --: | --: | --: | --: | --: | --: | :--- | --: |"]
    for c in cases:
        cost = ("—（上流に届かない）" if math.isinf(c.cost_per_1k)
                else f"{c.cost_per_1k:.4f}")
        if c.on_edge:
            edge = f"{c.edge_total_mb:.2f} MB"
            verdict = "載る" if c.edge_fits else "載らない"
            slack = f"{c.slack_mb:+.1f} MB"
        else:
            edge, verdict, slack = "0.00 MB", "—", "—"
        lines.append(f"| {c.edge_ratio:.0%} | {c.served_rps:.2f} | {c.replicas} "
                     f"| {c.utilization:.1%} | {cost} | {edge} | {verdict} "
                     f"| {slack} |")
    return "\n".join(lines)


def insight(cases: list[Case]) -> list[str]:
    """表から読み取れることを文章にする（気づきを人任せにしない）。"""
    finite = [c for c in cases if not math.isinf(c.cost_per_1k)]
    if len(finite) < 2:
        return ["比べられるケースが1つしかありません。割合を2つ以上指定してください。"]
    first, last = finite[0], finite[-1]
    lines = [
        f"- 上流に届く rps は {first.served_rps:.2f} → {last.served_rps:.2f} "
        f"（{first.served_rps / last.served_rps:.1f} 分の1）に減りました。",
        f"- ところが 1000リクエスト単価は {first.cost_per_1k:.4f} → "
        f"{last.cost_per_1k:.4f}（{last.cost_per_1k / first.cost_per_1k:.1f} 倍）"
        "に**悪化**しました。",
        f"- 理由は2つです。①レプリカ数は切り上げなので需要に比例して減らない "
        f"②下限 {FLOOR} 本を下回れない。結果として利用率が "
        f"{first.utilization:.1%} → {last.utilization:.1%} に落ちます。",
        "- **エッジ化の効果を金額で語るなら、台数を実際に減らせるところまで"
        "書いて初めて成立します。**",
    ]
    over = [c for c in cases if c.on_edge and not c.edge_fits]
    if over:
        lines.append(f"- 端末{cases[0].device} に載らないケースが "
                     f"{len(over)} 件あります。分類器の本数か端末を見直してください。")
    return lines


def memo(cases: list[Case], *, peak_rps: float, hourly: float,
         headroom: float, classifiers: int) -> str:
    """引き継げる Markdown。**①②③の区別と再計算手順を必ず含める。**"""
    point = best_point(slo=Slo())
    capacity = per_instance_rps(point.throughput_rps, headroom)
    device = cases[0].device if cases else "-"
    gen = generation_footprint()
    cls = classifier_footprint(classifiers)
    return "\n".join([
        "# エッジに出す割合を振った比較（みなと商事 ヘルプデスク回答 API）",
        "",
        f"- 測定条件（①実測）：{MEASURED_CONDITIONS}",
        "- **絶対値は再現しません。** レイテンシは実行ごとに2倍程度ぶれます。"
        "読み取るのは関係と向きです。",
        "",
        "## 1. 前提（変わったら数え直す入力）",
        "",
        "| 入力 | 値 | 種別 |",
        "| :--- | --: | :--- |",
        f"| ピークのリクエスト率 | {peak_rps:.2f} rps | ③ 要件 |",
        f"| 動作点の rps | {point.throughput_rps} | ① 実測（並列"
        f"{point.concurrency}・SLO を満たす最大の点） |",
        f"| 1インスタンスのスロット数 | {SLOTS_PER_INSTANCE} | "
        f"`-np {SLOTS_PER_INSTANCE}` |",
        f"| ヘッドルーム | {headroom:.0%} | ③ 運用の判断 |",
        f"| 1本の能力 | {capacity:.2f} rps | 計算値 |",
        f"| レプリカ数の下限 | {FLOOR} 本 | ③ 要件 |",
        f"| インスタンス時間単価 | {hourly:g} | ③ 読者が入れる（相対単位） |",
        f"| 対象端末 | 端末{device}（上限 "
        f"{cases[0].device_limit_mb if cases else 0:.1f} MB） | ③ 前提値 |",
        f"| エッジに置く分類器 | int8 × {classifiers} 本 | "
        f"① 実測サイズ（1本 {ONNX_INT8_MB} MB） |",
        "",
        "## 2. 比較表",
        "",
        table(cases),
        "",
        "## 3. 読み取れること",
        "",
        *insight(cases),
        "",
        "## 4. 端末に置くものの内訳",
        "",
        "| 置くもの | 重み | KVキャッシュ | 実行時 | 合計 |",
        "| :--- | --: | --: | --: | --: |",
        f"| 0.5B級 Q4_K_M で生成 | {gen.weights_mb:.1f} MB | {gen.kv_mb:.1f} MB "
        f"| {gen.runtime_mb:.1f} MB | {gen.total_mb:.1f} MB |",
        f"| int8 の分類器 × {classifiers} | {cls.weights_mb:.2f} MB | "
        f"{cls.kv_mb:.1f} MB | {cls.runtime_mb:.1f} MB | {cls.total_mb:.2f} MB |",
        "",
        "生成のフットプリントは KVキャッシュを 0 にしても大きく、**支配しているのは"
        "重み**です。系列長を短くする調整では届きません。",
        "",
        "## 5. 前提が変わったときの再計算手順",
        "",
        "1. 同時実行を振って測り直す（`src/session04/sweep.py`）。"
        "**SLO を満たす最大の点**を動作点に採る",
        "2. `--peak-rps` に新しいピークを入れ、レプリカ数と単価を出し直す",
        "3. 端末を変えたら `--device` を変え、余白が十分かを確認する",
        "4. 量子化を変えたら `src/session12/quant_report.py` で"
        "サイズ・速度・精度を測り直し、`ONNX_INT8_MB` を更新する",
        "5. 台数を減らせるかを運用と合意する（減らせないなら単価は下がらない）",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="エッジに出す割合を振って、クラウド側とエッジ側を並べる")
    parser.add_argument("--peak-rps", type=float, default=5.0)
    parser.add_argument("--ratios", type=float, nargs="+",
                        default=[0.0, 0.5, 0.8, 0.95],
                        help="エッジで解決する割合（0.0〜1.0）")
    parser.add_argument("--device", default="D", choices=sorted(DEVICES))
    parser.add_argument("--hourly", type=float, default=1.0,
                        help="インスタンス1台の1時間単価（相対単位）")
    parser.add_argument("--headroom", type=float, default=HEADROOM)
    parser.add_argument("--floor", type=int, default=FLOOR)
    parser.add_argument("--classifiers", type=int, default=2)
    parser.add_argument("--memo", action="store_true",
                        help="引き継げる Markdown を出す")
    args = parser.parse_args(argv)

    try:
        cases = sweep(peak_rps=args.peak_rps, ratios=tuple(args.ratios),
                      device=args.device, hourly=args.hourly,
                      headroom=args.headroom, floor=args.floor,
                      classifiers=args.classifiers)
    except ValueError as err:
        print(f"前提が不正です: {err}", file=sys.stderr)
        return 2

    if args.memo:
        print(memo(cases, peak_rps=args.peak_rps, hourly=args.hourly,
                   headroom=args.headroom, classifiers=args.classifiers))
    else:
        point = best_point(slo=Slo())
        print(f"測定条件: {MEASURED_CONDITIONS}")
        print(f"動作点  : 並列{point.concurrency}・"
              f"{point.throughput_rps} rps（①実測）")
        print(f"1本の能力: "
              f"{per_instance_rps(point.throughput_rps, args.headroom):.2f} rps"
              f"（ヘッドルーム {args.headroom:.0%} を引いた値）\n")
        print(table(cases))
        print()
        for line in insight(cases):
            print(line)
    return 0


__all__ = [
    "CLASSIFIER_RUNTIME_MB", "DEVICES", "FLOOR", "HEADROOM", "ONNX_INT8_MB",
    "Q4_K_M_MB", "RUNTIME_MB", "SEQ_LEN", "Case", "classifier_footprint",
    "cost_per_1k", "generation_footprint", "insight", "memo",
    "per_instance_rps", "replicas_for", "sweep", "table", "upstream_rps",
    "utilization",
]


if __name__ == "__main__":
    sys.exit(main())
