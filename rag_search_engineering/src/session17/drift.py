#!/usr/bin/env python3
"""検索品質の劣化（ドリフト）を検知する。

  python src/session17/drift.py
  python src/session17/drift.py --min-detectable

ここで見るのは「同じ質問をしても前より当たらなくなった」という**検索品質の劣化**である。
セッション16 の鮮度（データの遅れ）とは別物なので、指標もアラートも分けて設計する。

比較する2つの窓のうち「今週」は、章の説明のために**決定的な変換**で作った合成シナリオ
（新しいカテゴリが増えて略語クエリが急増し、その半分がゼロヒットになった週）である。
実測ではない。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from metrics import load_log, rows_by_type, summarize  # noqa: E402


@dataclass(frozen=True)
class AlertRule:
    """アラート1本。窓・閾値・誰が何をするかまでを1つにまとめる。"""

    name: str
    metric: str
    window: str
    threshold: str
    action: str
    owner: str


# 例。閾値と窓は「自分のトラフィック量で検知できる幅」に合わせて置き換える。
ALERT_RULES: tuple[AlertRule, ...] = (
    AlertRule("ゼロヒット急増", "ゼロヒット率", "24時間・500件以上",
              "ベースラインの2倍を超えた", "直近のゼロヒットを50件読み、型を分類する", "検索当番"),
    AlertRule("上位無クリック増", "上位無クリック率", "7日",
              "前週比 +5ポイント", "型別に分解し、悪化した型だけを評価セットで再現する", "検索当番"),
    AlertRule("型分布の変化", "クエリ型分布の L1 距離", "7日",
              "0.20 を超えた", "新しい需要か、流入経路の変化かを確かめる", "検索当番"),
    AlertRule("レイテンシ悪化", "p95 レイテンシ", "1時間",
              "SLO の 500ms を超えた", "候補数とリランク段を確認し、段数を落とす", "オンコール"),
    AlertRule("索引の入れ替え直後", "全指標", "切り替えから2時間",
              "どれか1つでも閾値を割った", "エイリアスを旧コレクションへ戻す", "オンコール"),
)


def type_distribution(log: list[dict]) -> dict[str, float]:
    rows = rows_by_type(log)
    total = sum(rows.values())
    return {qtype: n / total for qtype, n in rows.items()}


def l1_distance(p: dict[str, float], q: dict[str, float]) -> float:
    """2つの分布の L1 距離。0 なら同じ、2 が最大（＝重なりゼロ）。"""
    keys = set(p) | set(q)
    return sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def simulate_regression(log: list[dict]) -> list[dict]:
    """劣化した1週間を決定的に合成する（乱数を使わない）。

    略語クエリが5倍に増え、そのうち半分がゼロヒットになった状況を作る。
    """
    out: list[dict] = []
    for row in log:
        out.append(dict(row))
        if row["query_type"] != "abbrev":
            continue
        for k in range(4):
            dup = dict(row)
            dup["clicked_rank"] = None
            if k % 2 == 0:
                dup["n_results"] = 0
                dup["top_score"] = 0.0
            out.append(dup)
    return out


def window_report(log: list[dict]) -> dict:
    s = summarize(log)
    dist = type_distribution(log)
    return {
        "rows": s["rows"],
        "zero_hit_rate": s["zero_hit_rate"],
        "click_rate": s["click_rate"],
        "clicked": s["clicked"],
        "abbrev_share": dist.get("abbrev", 0.0),
        "distribution": dist,
    }


def compare(before: list[dict], after: list[dict]) -> dict:
    a, b = window_report(before), window_report(after)
    return {
        "before": a,
        "after": b,
        "zero_hit_delta": b["zero_hit_rate"] - a["zero_hit_rate"],
        "click_delta": b["click_rate"] - a["click_rate"],
        "clicked_delta": b["clicked"] - a["clicked"],
        "l1": l1_distance(a["distribution"], b["distribution"]),
    }


def binom_tail_ge(n: int, k: int, p: float) -> float:
    """二項分布の上側確率 P(X >= k)。漸化式で回すのでオーバーフローしない。"""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    if not 0.0 < p < 1.0:
        raise ValueError("p は 0 と 1 のあいだで指定してください")
    pmf = (1.0 - p) ** n
    total = 0.0
    for i in range(n + 1):
        if i >= k:
            total += pmf
        if i < n:
            pmf = pmf * (n - i) / (i + 1) * p / (1.0 - p)
    return total


def min_detectable_rate(n: int, p0: float, alpha: float = 0.01) -> float:
    """n 件の窓で「偶然ではない」と言える最小の悪化率。

    小さい窓では、率が何倍になっても偶然の範囲から出られない。
    アラートの閾値は、この値より下に置いても鳴るのはノイズだけになる。
    """
    for k in range(n + 1):
        if binom_tail_ge(n, k, p0) <= alpha:
            return k / n
    return 1.0


def main() -> None:
    parser = argparse.ArgumentParser(description="検索品質の劣化を検知する")
    parser.add_argument("--min-detectable", action="store_true",
                        help="窓の大きさごとに検知できる最小の悪化率を出す")
    args = parser.parse_args()

    log = load_log()
    after = simulate_regression(log)
    diff = compare(log, after)
    a, b = diff["before"], diff["after"]

    print("=== 先週（ベースライン）===")
    print(f"行数 : {a['rows']}")
    print(f"ゼロヒット率 : {a['zero_hit_rate'] * 100:.1f}%")
    print(f"クリック率 : {a['click_rate'] * 100:.1f}%")
    print(f"abbrev の割合 : {a['abbrev_share'] * 100:.1f}%")

    print("\n=== 今週（合成した劣化シナリオ）===")
    print(f"行数 : {b['rows']}")
    print(f"ゼロヒット率 : {b['zero_hit_rate'] * 100:.1f}%")
    print(f"クリック率 : {b['click_rate'] * 100:.1f}%")
    print(f"abbrev の割合 : {b['abbrev_share'] * 100:.1f}%")

    print("\n=== 差分 ===")
    print(f"クリック数 : {a['clicked']} -> {b['clicked']}"
          f"（差 {diff['clicked_delta']:+d}。率が下がったのは分母が増えたため）")
    print(f"クエリ型分布の L1 距離 : {diff['l1']:.4f}")

    if args.min_detectable:
        p0 = a["zero_hit_rate"]
        print(f"\n=== 窓の大きさと、検知できる最小のゼロヒット率（α=0.01・"
              f"ベースライン {p0 * 100:.1f}%）===")
        for n in (20, 50, 100, 500, 1000):
            print(f"{n} 件の窓 : {min_detectable_rate(n, p0) * 100:.1f}% 以上でないと有意にならない")

    print("\n=== アラート設計（例。あなたのトラフィック量に置き換える）===")
    for rule in ALERT_RULES:
        print(f"[{rule.name}] {rule.metric} / 窓 {rule.window} / 閾値 {rule.threshold}")
        print(f"  -> {rule.owner}: {rule.action}")


if __name__ == "__main__":
    main()
