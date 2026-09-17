"""意味のない乱数列を足すと、不純度ベースの重要度がどう壊れるかを見る（この章の山場）。

使い方:
    docker compose exec lab python src/session26/random_id_trap.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    RANDOM_ID,
    RANDOM_ID_MAX,
    fitted,
    impurity_table,
    permutation_table,
    save_figure,
)


def audit() -> dict:
    """random_id が 4 種類の見方でどう見えるかを 1 つの辞書にまとめる。"""
    plain = fitted()
    noisy = fitted(True)
    table = impurity_table(True)
    row = table.loc[table["feature"] == RANDOM_ID].iloc[0]
    top_split = table.sort_values("split", ascending=False).iloc[0]

    perm_test = permutation_table("test", True).set_index("feature")
    perm_train = permutation_table("train", True).set_index("feature")
    return {
        "n_rows": len(noisy["df"]),
        "n_columns": len(table),
        "roc_auc_plain": plain["roc_auc"],
        "roc_auc_noisy": noisy["roc_auc"],
        "split": int(row["split"]),
        "split_rank": int(row["split_rank"]),
        "gain": int(row["gain"]),  # 表示は int()（切り捨て）で統一する
        "gain_rank": int(row["gain_rank"]),
        "top_split_feature": str(top_split["feature"]),
        "top_split": int(top_split["split"]),
        "perm_test": float(perm_test.loc[RANDOM_ID, "mean"]),
        "perm_train": float(perm_train.loc[RANDOM_ID, "mean"]),
    }


def draw(path_name: str) -> str:
    """左に split、右に permutation（評価データ）。random_id だけ色を変える。"""
    impurity = impurity_table(True).sort_values("split")
    permutation = permutation_table("test", True).sort_values("mean")

    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.6))
    axes[0].barh(
        impurity["feature"],
        impurity["split"],
        color=["#e45756" if name == RANDOM_ID else "#c8c8c8" for name in impurity["feature"]],
    )
    axes[0].set_title("不純度ベース（split）では 2 位に見える")
    axes[0].set_xlabel("分割に使われた回数")

    axes[1].barh(
        permutation["feature"],
        permutation["mean"],
        xerr=permutation["std"],
        color=["#e45756" if name == RANDOM_ID else "#c8c8c8" for name in permutation["feature"]],
        capsize=3,
    )
    axes[1].axvline(0, color="#333333", linewidth=0.8)
    axes[1].set_title("permutation（評価データ）では 0 に張り付く")
    axes[1].set_xlabel("壊したときに落ちた ROC AUC")

    fig.suptitle("意味のない random_id は、どの重要度で見るかで扱いが変わる")
    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path.name


def main() -> None:
    result = audit()

    print("■ 1. 意味のない列を足す")
    print(f"random_id: 0〜{RANDOM_ID_MAX - 1:,} の一様乱数を {result['n_rows']:,} 行に 1 回だけ振った列")
    print("（訓練・評価に分ける前に振る。分けたあとに別々に振ると結果が変わります）")
    print()

    print("■ 2. 予測性能はほとんど変わらない")
    print(f"random_id なし: ROC AUC {result['roc_auc_plain']:.4f}")
    print(f"random_id あり: ROC AUC {result['roc_auc_noisy']:.4f}")
    print(f"差            : {result['roc_auc_noisy'] - result['roc_auc_plain']:+.3f}")
    print()

    print("■ 3. ところが不純度ベースの重要度では上位に来る")
    print(f"split: {result['split']:,}（{result['n_columns']} 列中 {result['split_rank']} 位）")
    print(f"gain : {result['gain']:,}（{result['n_columns']} 列中 {result['gain_rank']} 位）")
    print(f"split の 1 位は {result['top_split_feature']} の {result['top_split']:,}")
    print()

    print("■ 4. permutation importance では消える")
    print(f"評価データ: {result['perm_test']:+.4f}")
    print(f"訓練データ: {result['perm_train']:+.4f}")
    print()
    print("判断: random_id は予測に何も足していません（ROC AUC が動かない）。")
    print("      それでも木は『まだ分けられる場所』として使うので、分割回数は増えます。")
    print("      評価データの permutation importance だけが、この列を 0 と正しく答えます。")

    name = draw("s26_random_id.png")
    print(f"図を保存しました: outputs/{name}")


if __name__ == "__main__":
    main()
