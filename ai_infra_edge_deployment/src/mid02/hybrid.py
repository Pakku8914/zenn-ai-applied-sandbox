#!/usr/bin/env python3
"""ハイブリッド案：エッジで一次判定し、確度の低いものだけクラウドへ回す。

    python src/mid02/hybrid.py --demo             # 例示のマージンで感度分析
    python src/mid02/hybrid.py --from-report      # 自分の測定値（reports/mid02_edge.json）

振り分けの鍵は**マージン**（1位と2位の確率の差）である。セッション12 で
「マージンが小さい件は入れ替わる」と分かっているので、そこだけ人手か
クラウドに回す、というのが素直な設計になる。

**逆向き（クラウドで一次判定してエッジに回す）は作れない。**
言語モデルからは確率が取れないので、案Aの確度は2値しかない。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from src.mid02.compare import (  # noqa: E402
    EDGE_FIXED_COST, cloud_cost_per_1k, edge_cost_per_1k,
)

DEMO_MARGINS: tuple[float, ...] = tuple(round(0.02 + 0.03 * k, 2)
                                        for k in range(20))
"""**例示のための固定値であり、実測ではない。** 0.02 から 0.59 まで等間隔。
自分のモデルのマージンは --from-report で読み込む。"""

THRESHOLDS: tuple[float, ...] = (0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 1.00)

DEFAULT_TOTAL_REQUESTS = 1_000_000


@dataclass(frozen=True)
class Route:
    """しきい値ひとつに対する振り分けの結果。"""

    threshold: float
    total: int
    to_cloud: int

    @property
    def on_edge(self) -> int:
        return self.total - self.to_cloud

    @property
    def send_ratio(self) -> float:
        return self.to_cloud / self.total if self.total else 0.0


def route(margins, threshold: float) -> Route:
    """マージンがしきい値**未満**の件をクラウドへ回す。"""
    return Route(threshold, len(margins),
                 sum(1 for m in margins if m < threshold))


def sweep(margins, thresholds=THRESHOLDS,
          total_requests: float = DEFAULT_TOTAL_REQUESTS,
          fixed_cost: float = EDGE_FIXED_COST) -> list[dict]:
    """しきい値を振ったときの4つの軸。**同時に良くはならない**のが要点。"""
    base = edge_cost_per_1k(total_requests, fixed_cost)
    cloud = cloud_cost_per_1k()
    rows = []
    for t in thresholds:
        r = route(margins, t)
        rows.append({
            "threshold": t, "to_cloud": r.to_cloud, "on_edge": r.on_edge,
            "send_ratio": r.send_ratio,
            "cost_per_1k": base + r.send_ratio * cloud,
            "leaked_per_1k": r.send_ratio * 1000,      # 本文が端末外へ出る件数
            "offline_ok_per_1k": (1 - r.send_ratio) * 1000,
        })
    return rows


def load_margins(path: Path) -> tuple[float, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(float(m) for m in data["margins"])


def show(margins, source: str, total_requests: float, fixed_cost: float) -> None:
    cloud = cloud_cost_per_1k()
    print("=== ハイブリッドの感度分析（マージンのしきい値を振る）===")
    print(f"マージン: {source}")
    print(f"前提    : 総リクエスト数 {total_requests:,.0f} 件 / "
          f"エッジの固定費 {fixed_cost:g} /")
    print(f"          クラウドの1000件単価 {cloud:.4f}（いずれも相対単位）")
    print()
    print("| しきい値 | クラウドへ | エッジで | 送信率 | 1000件単価 | "
          "本文が出る件数 | 回線断でも処理 |")
    print("| --: | --: | --: | --: | --: | --: | --: |")
    rows = sweep(margins, THRESHOLDS, total_requests, fixed_cost)
    for row in rows:
        print(f"| {row['threshold']:.2f} | {row['to_cloud']} | "
              f"{row['on_edge']} | {row['send_ratio']:.1%} | "
              f"{row['cost_per_1k']:.4f} | {row['leaked_per_1k']:.0f} | "
              f"{row['offline_ok_per_1k']:.0f} |")
    full = rows[-1]["cost_per_1k"]
    print(f"\n-> しきい値 {THRESHOLDS[-1]:.2f}（全件クラウド）の単価 {full:.4f} は、"
          f"クラウド単独の {cloud:.4f} より高い。")
    print("   エッジの固定費を払ったうえでクラウドにも全件流すので、"
          "両方の費用が乗る。")
    print("-> 送信率を上げると単価・プライバシー・オフライン耐性の3つが"
          "同時に悪化する。")
    print("   精度が上がるのは「クラウドのほうが正しい」という前提が"
          "成り立つときだけ。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ハイブリッド案の感度分析")
    parser.add_argument("--demo", action="store_true",
                        help="例示のマージン（実測ではない）で計算する")
    parser.add_argument("--from-report", action="store_true",
                        help="reports/mid02_edge.json のマージンを使う")
    parser.add_argument("--edge-report", default="reports/mid02_edge.json")
    parser.add_argument("--total-requests", type=float,
                        default=DEFAULT_TOTAL_REQUESTS)
    parser.add_argument("--fixed-cost", type=float, default=EDGE_FIXED_COST)
    args = parser.parse_args(argv)

    if args.from_report:
        path = SANDBOX / args.edge_report
        if not path.exists():
            print(f"レポートがありません: {path}\n"
                  "先に src/mid02/edge_side.py を実行してください。",
                  file=sys.stderr)
            return 1
        margins = load_margins(path)
        source = f"{path.name} の実測値 {len(margins)} 件"
    else:
        margins = DEMO_MARGINS
        source = (f"例示の固定値 {len(DEMO_MARGINS)} 件"
                  f"（{DEMO_MARGINS[0]:.2f}〜{DEMO_MARGINS[-1]:.2f} の等間隔。"
                  "実測ではありません）")

    show(margins, source, args.total_requests, args.fixed_cost)
    return 0


if __name__ == "__main__":
    sys.exit(main())
