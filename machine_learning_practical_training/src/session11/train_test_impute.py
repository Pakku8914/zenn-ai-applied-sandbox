"""訓練データの統計量で検証データを埋める ― 8 行の toy でリークを目に見える形にする。

使い方:
    docker compose exec lab python src/session11/train_test_impute.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer

# 8 行だけの toy。前半 5 行を訓練、後半 3 行を検証とする。
# 「評価の高い行が訓練に、低い行が検証に寄っている」極端な分け方にしてあるので、
# fit の範囲を間違えると代入値がはっきり変わる。
TOY = pd.DataFrame({"rating": [5.0, 5.0, 4.0, 4.0, np.nan, 2.0, np.nan, 2.0]})


def fmt(values: np.ndarray) -> str:
    """代入後の値を横一列に並べて表示する。"""
    return "[" + ", ".join(f"{float(value):.4f}" for value in np.ravel(values)) + "]"


def main() -> None:
    train, test = TOY.iloc[:5], TOY.iloc[5:]
    print(f"訓練 {len(train)} 行 / 検証 {len(test)} 行（それぞれ 1 行が欠損）")
    print(f"  訓練データの観測平均: {train['rating'].mean():.4f}")
    print(f"  全データの観測平均  : {TOY['rating'].mean():.4f}")

    print("■ 正しい手順: fit は訓練データだけ。検証データには transform だけ")
    correct = SimpleImputer(strategy="mean").fit(train)
    print(f"  覚えた値 statistics_ = {float(correct.statistics_[0]):.4f}")
    print(f"  訓練を埋めた結果: {fmt(correct.transform(train))}")
    print(f"  検証を埋めた結果: {fmt(correct.transform(test))}")

    print("■ 誤った手順: 全データで fit する（検証データが代入値に混ざる）")
    leaked = SimpleImputer(strategy="mean").fit(TOY)
    print(f"  覚えた値 statistics_ = {float(leaked.statistics_[0]):.4f}")
    print(f"  訓練を埋めた結果: {fmt(leaked.transform(train))}")
    print(f"  検証を埋めた結果: {fmt(leaked.transform(test))}")
    print("  → 訓練データの欠損に入った 3.6667 は、検証データを見なければ計算できない値です")


if __name__ == "__main__":
    main()
