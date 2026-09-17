"""人工的にドリフトを起こして、監視が発火することを確かめる（本文 6 節）。

前の節で「PSI はすべて 0.003 未満」＝ドリフトが無いことを確認しました。
ただし、それだけでは**仕組みが壊れていても同じ結果に見えます**。
そこで、わざとデータを動かして「ちゃんと反応するか」を確かめます。

使い方:
    docker compose exec lab python src/session28/drift_injected.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    PSI_ACT,
    PSI_WATCH,
    QUANTITY_FRACTION,
    halves,
    quantity_drift,
    save_figure,
    shift_unit_price,
    unit_price_drift,
)

FIGURE_NAME = "s28_drift_shift.png"
SHOW_RATIO = 1.20  # 図に描く倍率（PSI が要再学習の線を超える倍率）
PRICE_RANGE = (0.0, 6000.0)  # ヒストグラムの範囲。3 本を同じ物差しで比べるために固定する


def draw(table, name: str = FIGURE_NAME) -> str:
    """左: 単価の分布（前半 / 後半 / 後半を 1.20 倍）。右: 倍率と PSI の関係。"""
    parts = halves()
    shifted = shift_unit_price(parts["after"], SHOW_RATIO)

    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.6))
    for values, label, color in [
        (parts["before"]["unit_price"], "前半（学習したころ）", "#4c78a8"),
        (parts["after"]["unit_price"], "後半（いま）", "#54a24b"),
        (shifted["unit_price"], f"後半を {SHOW_RATIO:.2f} 倍にした場合", "#e45756"),
    ]:
        axes[0].hist(
            values, bins=40, range=PRICE_RANGE, density=True, histtype="step", linewidth=1.6,
            label=label, color=color,
        )
    axes[0].set_title("単価の分布 ― 前半と後半はほぼ重なる")
    axes[0].set_xlabel("単価（円）")
    axes[0].set_ylabel("密度")
    axes[0].legend(fontsize=9)

    axes[1].plot(table["ratio"], table["psi"], marker="o", color="#4c78a8")
    axes[1].axhline(PSI_WATCH, color="#f58518", linestyle="--", linewidth=1.2, label=f"注意（{PSI_WATCH}）")
    axes[1].axhline(PSI_ACT, color="#e45756", linestyle="--", linewidth=1.2, label=f"要再学習（{PSI_ACT}）")
    for ratio, value in zip(table["ratio"], table["psi"]):
        axes[1].annotate(f"{value:.4f}", (ratio, value), textcoords="offset points", xytext=(6, 6), fontsize=9)
    axes[1].set_title("単価を何倍にすると PSI が反応するか")
    axes[1].set_xlabel("後半の単価にかけた倍率")
    axes[1].set_ylabel("PSI")
    axes[1].legend(loc="upper left", fontsize=9)

    fig.suptitle("監視は「動くことを確かめてから」信じる")
    return save_figure(fig, name)


def main() -> None:
    table = unit_price_drift()

    print("■ 1. 後半の単価を一律で上げてみる（監視の動作確認）")
    print("倍率  |    PSI | 判定")
    for row in table.itertuples():
        print(f"{row.ratio:.2f}  | {row.psi:>6.4f} | {row.judgement}")
    print()

    quantity = quantity_drift()
    print("■ 2. 数量を差し替えてみる（別の形のドリフト）")
    print(
        f"後半 {quantity['n_after']:,} 件のうち {quantity['n_changed']:,} 件"
        f"（{QUANTITY_FRACTION:.0%}）の数量を {quantity['value']} に差し替える"
    )
    print(f"差し替え前の PSI: {quantity['psi_plain']:.4f}（{quantity['judgement_plain']}）")
    print(f"差し替え後の PSI: {quantity['psi_injected']:.4f}（{quantity['judgement_injected']}）")
    print()

    print("■ 3. 判断")
    print("・単価が 5% 動いただけでは PSI は 0.1 に届きません（小さな変化には鈍い）")
    print("・20% 動くと 0.25 を超え、「要再学習」と判定されます")
    print("・数量のように値の種類が少ない列でも、3 割を入れ替えれば反応します")
    print("→ この確認をしておけば、実測の PSI が 0.003 未満だったことを")
    print("  「仕組みが壊れているから 0 に見えるだけ」と疑わずに済みます。")

    print(f"図を保存しました: outputs/{draw(table)}")


if __name__ == "__main__":
    main()
