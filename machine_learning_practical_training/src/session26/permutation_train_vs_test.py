"""permutation importance を訓練データと評価データの両方で測って見比べる。

使い方:
    docker compose exec lab python src/session26/permutation_train_vs_test.py
"""

from __future__ import annotations

from common import fitted, permutation_table


def show(title: str, table) -> None:
    """1 つの表を「順位・特徴量・平均の低下」で並べる。"""
    print(title)
    print(f"{'順位':<4}{'特徴量':<16}平均の低下")
    for rank, row in enumerate(table.itertuples(index=False), start=1):
        print(f"{str(rank) + '位':<4}{row.feature:<16}{row.mean:+.4f}")
    print()


def compare() -> dict:
    """訓練・評価の permutation importance を 1 つの表にまとめる。"""
    train = permutation_table("train").set_index("feature")
    test = permutation_table("test").set_index("feature")
    merged = train[["mean"]].join(test[["mean"]], lsuffix="_train", rsuffix="_test")
    merged["train_is_larger"] = merged["mean_train"] > merged["mean_test"]
    return {
        "table": merged.reset_index(),
        "n_train_larger": int(merged["train_is_larger"].sum()),
        "n_features": len(merged),
    }


def main() -> None:
    bundle = fitted()
    show(
        f"■ 1. 訓練データで測った permutation importance（{len(bundle['X_train']):,} 件）",
        permutation_table("train"),
    )
    show(
        f"■ 2. 評価データで測った permutation importance（{len(bundle['X_test']):,} 件）",
        permutation_table("test"),
    )

    result = compare()
    print("■ 3. 同じモデル・同じ手順なのに値が違う")
    print(f"{'特徴量':<16}{'訓練':>8}{'評価':>8}  訓練のほうが大きいか")
    for row in result["table"].itertuples(index=False):
        print(f"{row.feature:<16}{row.mean_train:>8.4f}{row.mean_test:>8.4f}  {row.train_is_larger}")
    print(f"訓練データのほうが大きく出た列: {result['n_train_larger']} / {result['n_features']}")
    print()
    print("判断: 訓練データで測ると『覚えた分』まで壊れるので、重要度が全体に大きく出ます。")
    print("      知りたいのは『未知のデータで効いているか』なので、評価データで測ります。")


if __name__ == "__main__":
    main()
