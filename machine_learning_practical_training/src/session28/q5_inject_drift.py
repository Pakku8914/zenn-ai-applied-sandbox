"""問題5 の解答: 人工的にドリフトを起こし、PSI が反応することを確かめる。

使い方:
    docker compose exec lab python src/session28/q5_inject_drift.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    PSI_ACT,
    PSI_WATCH,
    QUANTITY_FRACTION,
    quantity_drift,
    save_figure,
    unit_price_drift,
)

FIGURE_NAME = "s28_q5_drift.png"


def analyze() -> dict:
    """倍率ごとの PSI と、数量を差し替えたときの PSI をまとめる。"""
    table = unit_price_drift()
    quantity = quantity_drift()
    fired = table.loc[table["psi"] >= PSI_WATCH]
    return {
        "table": table,
        "quantity": quantity,
        "first_fired_ratio": float(fired["ratio"].iloc[0]) if len(fired) else None,
        "n_not_stable": int((table["judgement"] != "安定").sum()),
        "n_ratios": int(len(table)),
    }


def draw(result: dict, name: str = FIGURE_NAME) -> str:
    """5 通りの操作を横に並べ、注意・要再学習の線と比べる。"""
    table = result["table"]
    labels = [f"単価 ×{ratio:.2f}" for ratio in table["ratio"]] + [f"数量 {QUANTITY_FRACTION:.0%} を 5 に"]
    values = list(table["psi"]) + [result["quantity"]["psi_injected"]]
    colors = ["#4c78a8" if value < PSI_ACT else "#e45756" for value in values]

    fig, ax = plt.subplots(figsize=(9.0, 4.6))
    ax.bar(labels, values, color=colors, width=0.55)
    ax.axhline(PSI_WATCH, color="#f58518", linestyle="--", linewidth=1.2, label=f"注意（{PSI_WATCH}）")
    ax.axhline(PSI_ACT, color="#e45756", linestyle="--", linewidth=1.2, label=f"要再学習（{PSI_ACT}）")
    for index, value in enumerate(values):
        ax.text(index, value + 0.02, f"{value:.4f}", ha="center", fontsize=9)
    ax.set_ylim(0.0, 1.05)
    ax.set_ylabel("PSI")
    ax.set_title("どれだけ動かせば監視が発火するか")
    ax.legend(loc="upper left", fontsize=9)
    return save_figure(fig, name)


def main() -> None:
    result = analyze()
    table = result["table"]
    quantity = result["quantity"]

    print("■ 1. 後半の単価に倍率をかける")
    print("倍率  |    PSI | 判定")
    for row in table.itertuples():
        print(f"{row.ratio:.2f}  | {row.psi:>6.4f} | {row.judgement}")
    print(f"はじめて「注意」を超える倍率: {result['first_fired_ratio']:.2f}")
    print()

    print("■ 2. 数量を差し替える")
    print(
        f"後半 {quantity['n_after']:,} 件のうち {quantity['n_changed']:,} 件"
        f"（{QUANTITY_FRACTION:.0%}）を数量 {quantity['value']} に差し替える"
    )
    print(f"差し替え前: {quantity['psi_plain']:.4f}（{quantity['judgement_plain']}）")
    print(f"差し替え後: {quantity['psi_injected']:.4f}（{quantity['judgement_injected']}）")
    print()

    print(f"■ 3. 「安定」でなくなった倍率の数: {result['n_not_stable']} / {result['n_ratios']}")
    print()

    print("■ 4. 5% の変化が見逃される理由（3 文）")
    print("PSI はビンに入る件数の比率で測るので、境界をまたがない移動は数に出ません。")
    print("単価が 5% 上がっても、多くの注文は同じビンの中にとどまります。")
    print("小さくても見逃したくない変化があるなら、平均や中位数を別に監視します。")

    print(f"図を保存しました: outputs/{draw(result)}")


if __name__ == "__main__":
    main()
