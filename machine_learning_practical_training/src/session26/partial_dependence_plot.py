"""部分依存プロット ― 1 つの列だけを動かすと予測はどう動くかを見る。

使い方:
    docker compose exec lab python src/session26/partial_dependence_plot.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import GRID_RESOLUTION, fitted, pdp_int_error, pdp_table, save_figure

TARGETS = [("unit_price", "単価（円）"), ("body_length", "レビュー本文の長さ（文字）")]


def show(title: str, table) -> None:
    """部分依存の表を「動かす値 → 予測確率の平均」で並べる。"""
    print(title)
    print(f"{'動かす値':>8}{'高評価の確率の平均':>12}")
    for row in table.itertuples(index=False):
        print(f"{row.grid:>8,.0f}{row.average:>12.4f}")
    print()


def draw(tables: dict, path_name: str) -> str:
    """2 つの列の部分依存を折れ線で並べる（縦軸は確率なので 0〜1 にそろえる）。"""
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.2))
    for ax, (feature, label) in zip(axes, TARGETS):
        table = tables[feature]
        ax.plot(table["grid"], table["average"], marker="o", color="#4c78a8")
        ax.set_ylim(0.0, 1.0)
        ax.set_xlabel(label)
        ax.set_ylabel("高評価と予測される確率の平均")
        ax.set_title(f"{feature} の部分依存")
        ax.grid(alpha=0.3)
    fig.suptitle("1 つの列だけを動かしたときの予測の平均（他の列は実データのまま）")
    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path.name


def main() -> None:
    bundle = fitted()

    print("■ 1. int 型のまま渡すと拒否される")
    message = pdp_int_error("unit_price")
    # 文面は長いので、最初のコロンまで（要旨の部分）だけを表示する
    print(f"ValueError: {message.split(':', 1)[0]}: ...")
    print('対処: 動かす列を astype("float64") にしてから渡す')
    print()

    tables = {feature: pdp_table(feature) for feature, _ in TARGETS}
    show(
        f"■ 2. unit_price を動かす（grid_resolution={GRID_RESOLUTION}・訓練データ {len(bundle['X_train']):,} 件で平均）",
        tables["unit_price"],
    )
    show("■ 3. body_length を動かす", tables["body_length"])

    price = tables["unit_price"]
    length = tables["body_length"]
    print("読み取り:")
    print(
        f"単価が {price['grid'].iloc[0]:,.0f} 円から {price['grid'].iloc[-1]:,.0f} 円に上がると、"
        f"確率の平均は {price['average'].iloc[0]:.4f} から {price['average'].iloc[-1]:.4f} に下がります。"
    )
    print(
        f"本文の長さが {length['grid'].iloc[0]:,.0f} 文字から {length['grid'].iloc[-1]:,.0f} 文字に伸びると、"
        f"確率の平均は {length['average'].iloc[0]:.4f} から {length['average'].iloc[-1]:.4f} に下がります。"
    )
    print("どちらも『この列を動かせば結果が変わる』という意味ではありません（因果ではありません）。")

    name = draw(tables, "s26_partial_dependence.png")
    print(f"図を保存しました: outputs/{name}")


if __name__ == "__main__":
    main()
