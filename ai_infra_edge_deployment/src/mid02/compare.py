#!/usr/bin/env python3
"""同じ表に並べる（中間プロジェクト2）。

    python src/mid02/compare.py --check       # 測定条件の突き合わせ（比較可否の判定）
    python src/mid02/compare.py --cost        # 単位コストの構造と損益分岐
    python src/mid02/compare.py --dist        # モデルを 1,000 台に配る時間
    python src/mid02/compare.py --breakdown   # レイテンシの差を3項に分解する
    python src/mid02/compare.py --reference   # 本書の参考値で埋めた7軸の表

**推論サーバもモデルも要らない。** 測定と判定を分けてあるので、条件の
書き漏れは机の上で直せる。金額は書かない（相対単位で計算する）。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from infrakit.cost import SelfHosted  # noqa: E402
from src.session11.edge_budget import rtt_floor_ms  # noqa: E402

REPORTS = SANDBOX / "reports"

MEASURED_CONDITIONS = ("2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB / "
                       "Python 3.12.13 / llama.cpp -t 2")

# ---------------------------------------------------------------------------
# 1. 条件の突き合わせ
# ---------------------------------------------------------------------------

MUST_MATCH: tuple[str, ...] = ("input_set", "n_inputs", "output_form",
                               "measure_point", "median_of")
"""**揃っていなければ比較不可**にするキー。ここが違う表は結論を出せない。"""

MUST_DECLARE: tuple[str, ...] = ("model", "network_roundtrip", "warmup")
"""揃わなくてよいが、**両側に書かれていなければ比較不可**にするキー。
揃えられない条件を「書いていない」のと「揃っている」のは別物である。"""


@dataclass(frozen=True)
class Match:
    matched: tuple[str, ...]
    mismatched: tuple[tuple[str, str, str], ...]
    missing: tuple[str, ...]
    declared: tuple[tuple[str, str, str], ...]

    @property
    def comparable(self) -> bool:
        return not self.mismatched and not self.missing

    def verdict(self) -> str:
        if not self.comparable:
            return "比較不可"
        return ("比較可（ただし揃えられない条件あり）" if self.declared
                else "比較可")


def check_conditions(cloud: dict, edge: dict) -> Match:
    matched: list[str] = []
    mismatched: list[tuple[str, str, str]] = []
    missing: list[str] = []
    declared: list[tuple[str, str, str]] = []
    for key in MUST_MATCH + MUST_DECLARE:
        if key not in cloud or key not in edge:
            missing.append(key)
            continue
        a, b = str(cloud[key]), str(edge[key])
        if a == b:
            matched.append(key)
        elif key in MUST_DECLARE:
            declared.append((key, a, b))
        else:
            mismatched.append((key, a, b))
    return Match(tuple(matched), tuple(mismatched), tuple(missing),
                 tuple(declared))


# ---------------------------------------------------------------------------
# 2. 単価（相対単位。金額は書かない）
# ---------------------------------------------------------------------------

CLOUD_HOURLY = 1.0        # ③ 前提値：インスタンス1時間の値段を 1 と置く
CLOUD_INSTANCES = 3       # セッション9 の容量計画
CLOUD_RPS = 1.13          # ① 実測：動作点（並列2）の rps
CLOUD_UTILIZATION = 0.7   # セッション9 のヘッドルーム 30% の裏返し
EDGE_FIXED_COST = 100.0   # ③ 前提値：配布・検証・仕組み作りの1回払い（例示）

REQUEST_SCALE: tuple[float, ...] = (10_000, 100_000, 1_000_000, 10_000_000)


def cloud_cost_per_1k() -> float:
    """件数に**依存しない**。利用率が同じなら一定（セッション10 の式）。"""
    return SelfHosted(CLOUD_HOURLY, CLOUD_INSTANCES, CLOUD_RPS,
                      CLOUD_UTILIZATION).cost_per_1k_requests


def edge_cost_per_1k(total_requests: float,
                     fixed_cost: float = EDGE_FIXED_COST) -> float:
    """件数に**反比例**する。使えば使うほど安くなる。"""
    return float("inf") if total_requests <= 0 else \
        fixed_cost / total_requests * 1000.0


def breakeven_requests(fixed_cost: float = EDGE_FIXED_COST) -> float:
    """エッジの固定費を、クラウドの1リクエスト単価で割る。
    セッション10 の損益分岐（固定費 ÷ API の1リクエスト単価）と**同じ式**。"""
    return fixed_cost / (cloud_cost_per_1k() / 1000.0)


def cost_rows(fixed_cost: float = EDGE_FIXED_COST) -> list[dict]:
    cloud = cloud_cost_per_1k()
    points = sorted(set(REQUEST_SCALE) | {round(breakeven_requests(fixed_cost))})
    rows = []
    for n in points:
        edge = edge_cost_per_1k(n, fixed_cost)
        cheaper = ("同じ（分岐点）" if abs(edge - cloud) < 1e-4
                   else "エッジ" if edge < cloud else "クラウド")
        rows.append({"requests": n, "edge": edge, "cloud": cloud,
                     "cheaper": cheaper})
    return rows


# ---------------------------------------------------------------------------
# 3. 配布時間（② 物理計算 ＋ ③ 前提値）
# ---------------------------------------------------------------------------

MB = 1024 ** 2
SIZE_FP32_MB = 70.13      # ① 実測（2026-08-15）
SIZE_INT8_MB = 17.56      # ① 実測（同日。fp32 の 25.0%）
DEVICES = 1000            # ③ 前提値（セッション11）
LINE_MBPS = 100.0         # ③ 前提値（セッション11）


def distribution_seconds(size_mb: float, devices: int = DEVICES,
                         mbps: float = LINE_MBPS) -> float:
    """理論下限。回線を独占できたと仮定した値で、実際はこれを必ず上回る。"""
    return size_mb * MB * 8 / (mbps * 1_000_000) * devices


# ---------------------------------------------------------------------------
# 4. 差の内訳
# ---------------------------------------------------------------------------

CLOUD_TTFT_P50_MS = 155.0   # ① 実測（Q4_K_M・-c 2048 -np 2・並列1・max_tokens=48）
EDGE_P50_MS = 0.29          # ① 実測（int8・スレッド1・50回の中央値）
QUEUE_AT_C4_MS = 1772.0     # ① 実測（並列4 の TTFT p50）
DISTANCE_KM = 500.0         # ③ 前提値


def latency_breakdown(cloud_ms: float = CLOUD_TTFT_P50_MS,
                      edge_ms: float = EDGE_P50_MS,
                      distance_km: float = DISTANCE_KM) -> dict:
    """「N 倍速い」を3項に分ける。**ここが比較レポートの価値の中心。**"""
    rtt = rtt_floor_ms(distance_km)                 # ② 物理計算
    cloud_with_small_model = edge_ms + rtt          # 同じ分類器をクラウドに置いたら
    total = cloud_ms / edge_ms
    edge_effect = cloud_with_small_model / edge_ms
    return {"total_ratio": total, "edge_effect": edge_effect,
            "task_effect": total / edge_effect, "rtt_floor_ms": rtt,
            "cloud_with_small_model_ms": cloud_with_small_model,
            "distance_km": distance_km}


# ---------------------------------------------------------------------------
# 5. 表示
# ---------------------------------------------------------------------------


def show_cost(fixed_cost: float = EDGE_FIXED_COST) -> None:
    cloud = cloud_cost_per_1k()
    print("=== 単位コストの構造（相対単位。金額は書きません）===")
    print(f"クラウド : ({CLOUD_HOURLY:g} × {CLOUD_INSTANCES}) ÷ "
          f"({CLOUD_RPS:g} × 3600 × {CLOUD_INSTANCES} × {CLOUD_UTILIZATION:g})"
          f" × 1000 = {cloud:.4f} / 1000件（件数に依存しない）")
    print(f"エッジ   : 固定費 {fixed_cost:g} ÷ 総件数 × 1000（件数に反比例）")
    print(f"損益分岐 : {fixed_cost:g} ÷ {cloud / 1000.0:.8f} = "
          f"{breakeven_requests(fixed_cost):,.0f} 件")
    print()
    print("| 総リクエスト数 | エッジ | クラウド | 安いのは |")
    print("| --: | --: | --: | :--- |")
    for row in cost_rows(fixed_cost):
        print(f"| {row['requests']:,.0f} | {row['edge']:.4f} | "
              f"{row['cloud']:.4f} | {row['cheaper']} |")
    print("\n-> 「エッジは安い」も「クラウドは安い」も、"
          "件数を書かないと嘘になります。")


def show_distribution() -> None:
    print(f"=== モデルを {DEVICES:,} 台に配る時間"
          f"（理論下限・回線 {LINE_MBPS:.1f} Mbps）===")
    print("| 形式 | サイズ | 1 台 | 1,000 台 |")
    print("| :--- | --: | --: | --: |")
    rows = (("fp32", SIZE_FP32_MB), ("int8", SIZE_INT8_MB))
    seconds = {}
    for label, size in rows:
        one = distribution_seconds(size, 1)
        many = distribution_seconds(size)
        seconds[label] = many
        print(f"| {label} | {size:.2f} MB | {one:.1f} 秒 | "
              f"{many:,.1f} 秒（{many / 60:.1f} 分） |")
    print(f"-> int8 にすると配布時間は {seconds['fp32'] / seconds['int8']:.1f} 倍"
          "短い（サイズ比の逆数そのまま）。")
    print(f"-> 端末数 {DEVICES:,} 台と回線 {LINE_MBPS:.1f} Mbps は"
          "セッション11 の前提値です。")


def show_breakdown(distance_km: float = DISTANCE_KM) -> None:
    b = latency_breakdown(distance_km=distance_km)
    print("=== レイテンシの差を3項に分解する ===")
    print(f"前提: クラウド {CLOUD_TTFT_P50_MS:.0f} ms（TTFT p50・実測）/ "
          f"エッジ {EDGE_P50_MS:.2f} ms（int8 定常 p50・実測）")
    print(f"      距離 {b['distance_km']:.0f} km（前提値）→ "
          f"往復の物理下限 {b['rtt_floor_ms']:.2f} ms（物理計算）")
    print()
    print(f"全体の比            : {CLOUD_TTFT_P50_MS:.0f} ÷ {EDGE_P50_MS:.2f} = "
          f"{b['total_ratio']:.1f} 倍")
    print(f"同じ分類器をクラウドに: {EDGE_P50_MS:.2f} + {b['rtt_floor_ms']:.2f} = "
          f"{b['cloud_with_small_model_ms']:.2f} ms")
    print(f"  ① エッジであること : {b['cloud_with_small_model_ms']:.2f} ÷ "
          f"{EDGE_P50_MS:.2f} = {b['edge_effect']:.1f} 倍")
    print(f"  ② タスクの切り出し : {b['total_ratio']:.1f} ÷ "
          f"{b['edge_effect']:.1f} = {b['task_effect']:.1f} 倍")
    print(f"  ③ 待ち行列         : 並列1 ではほぼ 0。並列4 では TTFT p50 が "
          f"{QUEUE_AT_C4_MS:,.0f} ms"
          f"（+{QUEUE_AT_C4_MS - CLOUD_TTFT_P50_MS:,.0f} ms）")
    print("\n-> ② が支配的なら、打つ手は「エッジに移す」ではなく"
          "「クラウドでも小さいモデルに替える」。")
    print("-> ① が支配的で距離が縮められないなら、エッジ以外に手がない。")


def show_reference() -> None:
    """本書の参考値で埋めた7軸の表。**自分の測定値で置き換えて使う。**"""
    cloud = cloud_cost_per_1k()
    b = latency_breakdown()
    dist_int8 = distribution_seconds(SIZE_INT8_MB)
    print("=== 7軸の比較表（参考値。測定条件は "
          f"{MEASURED_CONDITIONS}）===")
    print("| # | 軸 | 案A クラウド | 案B エッジ | 出どころ |")
    print("| --: | :--- | :--- | :--- | :--- |")
    print("| 1 | 区分IDまで p50 | 自分の測定値 | 自分の測定値 | 実測 |")
    print(f"| 1' | 最初の反応 TTFT | {CLOUD_TTFT_P50_MS:.0f} ms"
          "（max_tokens=48） | —（一度に返る） | 実測 |")
    print(f"| 2 | スループット | {CLOUD_RPS:g} rps（動作点・並列2） | "
          f"{1000.0 / EDGE_P50_MS:,.0f} 件/秒（逐次の上限） | 実測＋式 |")
    print(f"| 3 | 1000件単価 | {cloud:.4f}（件数に依存しない） | "
          f"固定費{EDGE_FIXED_COST:g} ÷ 件数 × 1000 | 式（相対単位） |")
    print(f"| 3' | 分岐点 | — | {breakeven_requests():,.0f} 件で同額 | 式 |")
    print("| 4 | 精度（同値性） | —（基準となる fp32 版が無い） | "
          "最大差／マージン別一致率 | 実測 |")
    print("| 4' | 精度（形式違反率） | 自分の測定値（件数を書く） | "
          "0%（構造的に起きない） | 実測＋構造 |")
    print("| 5 | オフライン耐性 | 0 件（回線断で全滅） | 全件 | 構成から自明 |")
    print("| 6 | プライバシー | 本文が全件端末外へ出る | 出ない | 実装の契約 |")
    print(f"| 7 | 運用の手間 | 1 回のデプロイで全員に反映 | "
          f"{DEVICES:,} 台に配布（下限 {dist_int8 / 60:.1f} 分） | 式＋前提値 |")
    print(f"\n差の内訳: {b['total_ratio']:.1f} 倍 = "
          f"タスクの切り出し {b['task_effect']:.1f} 倍 × "
          f"エッジであること {b['edge_effect']:.1f} 倍")
    print("注意: 1' の TTFT は max_tokens=48 の実測値です。"
          "分類（max_tokens=8）の条件では測っていないので、同じ表に置くときは"
          "条件を必ず書いてください。")


def show_check(cloud_path: Path, edge_path: Path) -> int:
    missing_files = [p for p in (cloud_path, edge_path) if not p.exists()]
    if missing_files:
        print("=== 測定条件の突き合わせ ===")
        for p in missing_files:
            print(f"レポートがありません: {p}")
        print("先に cloud_side.py と edge_side.py を実行してください。")
        return 1

    cloud = json.loads(cloud_path.read_text(encoding="utf-8"))["conditions"]
    edge = json.loads(edge_path.read_text(encoding="utf-8"))["conditions"]
    m = check_conditions(cloud, edge)

    print("=== 測定条件の突き合わせ ===")
    print(f"判定: {m.verdict()}")
    print(f"\n揃っている条件（{len(m.matched)} 件）")
    print("  " + " / ".join(m.matched) if m.matched else "  なし")
    if m.declared:
        print(f"\n揃えられない条件（宣言済み・{len(m.declared)} 件）")
        for key, a, b in m.declared:
            print(f"  {key:<17}: {a} ⇔ {b}")
    if m.mismatched:
        print(f"\n揃っていない条件（{len(m.mismatched)} 件・比較不可の原因）")
        for key, a, b in m.mismatched:
            print(f"  {key:<17}: {a} ⇔ {b}")
    if m.missing:
        print(f"\n書かれていない条件（{len(m.missing)} 件・比較不可の原因）")
        print("  " + " / ".join(m.missing))

    if m.comparable:
        print("\n-> 揃えられない条件は「揃えたふり」をせず、"
              "差の内訳に分解して説明します。")
        return 0
    print("\n-> 表を作らずに測り直してください。"
          "判定を無視して作った表は、表が無いより悪いです。")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="クラウド案とエッジ案を同じ表に並べる")
    parser.add_argument("--check", action="store_true", help="条件の突き合わせ")
    parser.add_argument("--cost", action="store_true", help="単位コストの構造")
    parser.add_argument("--dist", action="store_true", help="配布時間")
    parser.add_argument("--breakdown", action="store_true", help="差の内訳")
    parser.add_argument("--reference", action="store_true", help="参考値の7軸表")
    parser.add_argument("--fixed-cost", type=float, default=EDGE_FIXED_COST)
    parser.add_argument("--distance-km", type=float, default=DISTANCE_KM)
    parser.add_argument("--cloud-report", default="reports/mid02_cloud.json")
    parser.add_argument("--edge-report", default="reports/mid02_edge.json")
    args = parser.parse_args(argv)

    if args.check:
        return show_check(SANDBOX / args.cloud_report, SANDBOX / args.edge_report)
    if args.cost:
        show_cost(args.fixed_cost)
        return 0
    if args.dist:
        show_distribution()
        return 0
    if args.breakdown:
        show_breakdown(args.distance_km)
        return 0
    if args.reference:
        show_reference()
        return 0

    show_cost(args.fixed_cost)
    print()
    show_distribution()
    print()
    show_breakdown(args.distance_km)
    print()
    show_reference()
    return 0


if __name__ == "__main__":
    sys.exit(main())
