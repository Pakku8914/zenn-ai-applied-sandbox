"""3 種類の重要度（不純度ベース・permutation・SHAP の前半）を同じモデルで並べる。

使い方:
    docker compose exec lab python src/session26/three_importances.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 画面のない環境なのでファイルに保存する
import matplotlib.pyplot as plt

from common import (
    N_REPEATS,
    SCORING,
    fitted,
    impurity_table,
    permutation_table,
    save_figure,
)

TOP_N = 5  # gain と順位比較で並べる件数


def show_split(table) -> None:
    """split（分割に使われた回数）を全列ぶん並べる。"""
    print("■ 1. 不純度ベースの重要度 ― split（その列で分割した回数）")
    print(f"{'順位':<4}{'特徴量':<16}{'split':>7}")
    for row in table.sort_values("split", ascending=False).itertuples(index=False):
        print(f"{str(row.split_rank) + '位':<4}{row.feature:<16}{row.split:>7,}")
    print(f"合計 {int(table['split'].sum()):,}（木 200 本 × 1 本あたり 30 分割）")
    print()


def show_gain(table) -> None:
    """gain（分割で減った不純度の合計）を上位だけ並べる。"""
    print("■ 2. 不純度ベースの重要度 ― gain（その列の分割で減った不純度の合計）")
    print(f"{'順位':<4}{'特徴量':<16}{'gain':>9}")
    ordered = table.sort_values("gain", ascending=False).head(TOP_N)
    for row in ordered.itertuples(index=False):
        # 小さな gain は丸め方で ±1 変わるので、表示は int()（切り捨て）で統一する
        print(f"{str(row.gain_rank) + '位':<4}{row.feature:<16}{int(row.gain):>9,}")
    print("6 位以下は category を One-Hot で開いた残りの 4 列です。")
    print()


def show_permutation(table, n_rows: int) -> None:
    """permutation importance を「平均の低下 ± ばらつき」で並べる。"""
    print(f"■ 3. permutation importance（評価データ {n_rows:,} 件・scoring={SCORING}・n_repeats={N_REPEATS}）")
    print(f"{'順位':<4}{'特徴量':<16}平均の低下 ± ばらつき")
    for rank, row in enumerate(table.itertuples(index=False), start=1):
        print(f"{str(rank) + '位':<4}{row.feature:<16}{row.mean:+.4f} ± {row.std:.4f}")
    print()


def show_ranks(impurity, permutation) -> None:
    """3 つの重要度で上位 5 位の並びを見比べる。"""
    split_order = list(impurity.sort_values("split", ascending=False)["feature"].head(TOP_N))
    gain_order = list(impurity.sort_values("gain", ascending=False)["feature"].head(TOP_N))
    perm_order = list(permutation["feature"].head(TOP_N))

    print("■ 4. 同じモデルなのに、上位の並びが 3 つとも違う")
    print(f"{'順位':<4}{'split':<16}{'gain':<16}permutation（評価）")
    for index in range(TOP_N):
        print(f"{str(index + 1) + '位':<4}{split_order[index]:<16}{gain_order[index]:<16}{perm_order[index]}")
    print()
    print(f"split と gain で 1 位が入れ替わるか: {split_order[0] != gain_order[0]}")
    print(f"gain と permutation で 2 位が入れ替わるか: {gain_order[1] != perm_order[1]}")


def draw(impurity, permutation, path_name: str) -> str:
    """3 種類の重要度を横棒 3 枚で並べる（単位が違うので軸は共有しない）。"""
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4))

    split_sorted = impurity.sort_values("split")
    axes[0].barh(split_sorted["feature"], split_sorted["split"], color="#4c78a8")
    axes[0].set_title("① 不純度ベース：split（回数）")
    axes[0].set_xlabel("分割に使われた回数")

    gain_sorted = impurity.sort_values("gain").tail(TOP_N)
    axes[1].barh(gain_sorted["feature"], gain_sorted["gain"], color="#72b7b2")
    axes[1].set_title("② 不純度ベース：gain（改善量・上位 5 件）")
    axes[1].set_xlabel("減らした不純度の合計")

    perm_sorted = permutation.sort_values("mean")
    axes[2].barh(
        perm_sorted["feature"],
        perm_sorted["mean"],
        xerr=perm_sorted["std"],
        color="#e45756",
        capsize=3,
    )
    axes[2].axvline(0, color="#333333", linewidth=0.8)
    axes[2].set_title("③ permutation（評価データ・AUC の低下）")
    axes[2].set_xlabel("壊したときに落ちた ROC AUC")

    fig.suptitle("同じ LightGBM を 3 種類の重要度で見る ― 測っているものが違う")
    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path.name


def main() -> None:
    bundle = fitted()
    impurity = impurity_table()
    permutation = permutation_table("test")

    show_split(impurity)
    show_gain(impurity)
    show_permutation(permutation, len(bundle["X_test"]))
    show_ranks(impurity, permutation)

    name = draw(impurity, permutation, "s26_importance_compare.png")
    print(f"図を保存しました: outputs/{name}")


if __name__ == "__main__":
    main()
