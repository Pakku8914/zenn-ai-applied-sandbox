"""問題3: 同じ permutation importance を訓練データでも計算し、どこが違うかを並べる。

使い方:
    docker compose exec lab python src/session26/q3_train_vs_eval.py
"""

from __future__ import annotations

from common import fitted, permutation_table


def summary() -> dict:
    """訓練と評価を 1 つの表にし、どちらが大きいかを列ごとに判定する。"""
    train = permutation_table("train").set_index("feature")
    test = permutation_table("test").set_index("feature")
    merged = train[["mean"]].join(test[["mean"]], lsuffix="_train", rsuffix="_test")
    merged["train_is_larger"] = merged["mean_train"] > merged["mean_test"]
    return {
        "table": merged.reset_index(),
        "n_train": len(fitted()["X_train"]),
        "n_test": len(fitted()["X_test"]),
        "n_train_larger": int(merged["train_is_larger"].sum()),
        "n_features": len(merged),
        "all_train_larger": bool(merged["train_is_larger"].all()),
        "train_top": str(merged["mean_train"].idxmax()),
        "test_top": str(merged["mean_test"].idxmax()),
    }


def main() -> None:
    result = summary()

    print(f"■ 1. 訓練 {result['n_train']:,} 件と評価 {result['n_test']:,} 件で並べる")
    print(f"{'特徴量':<16}{'訓練':>8}{'評価':>8}  訓練のほうが大きいか")
    for row in result["table"].itertuples(index=False):
        print(f"{row.feature:<16}{row.mean_train:>8.4f}{row.mean_test:>8.4f}  {row.train_is_larger}")
    print()

    print("■ 2. 判定")
    print(f"訓練のほうが大きく出た列: {result['n_train_larger']} / {result['n_features']}")
    print(f"すべての列で訓練が大きいか: {result['all_train_larger']}")
    print(f"訓練での 1 位: {result['train_top']}")
    print(f"評価での 1 位: {result['test_top']}")
    print()
    print("■ 3. なぜ評価データで測るのか（3 文以内）")
    print("訓練データでは、モデルが覚えてしまった細部まで『壊れる』ので重要度が大きく出ます。")
    print("知りたいのは未知のデータで効いているかどうかなので、学習に使っていないデータで測ります。")
    print("訓練データの値は『どれだけ覚えたか』を表していて、『どれだけ役に立つか』ではありません。")


if __name__ == "__main__":
    main()
