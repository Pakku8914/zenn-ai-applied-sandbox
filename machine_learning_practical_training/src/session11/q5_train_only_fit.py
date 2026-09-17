"""問題5: 訓練データの統計量で検証データを埋める（リーク回避）。

使い方:
    docker compose exec lab python src/session11/q5_train_only_fit.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split

from common import load_customers

# 前半 5 行を訓練、後半 3 行を検証。極端に偏らせて、fit の範囲の違いを見えるようにする
TOY = pd.DataFrame({"rating": [5.0, 5.0, 4.0, 4.0, np.nan, 2.0, np.nan, 2.0]})


def values_of(array) -> list[float]:
    """代入後の値を丸めて並べる（表示のため）。"""
    return [round(float(value), 4) for value in np.ravel(array)]


def main() -> None:
    train, test = TOY.iloc[:5], TOY.iloc[5:]
    correct = SimpleImputer(strategy="mean").fit(train)  # 訓練だけで fit
    leaked = SimpleImputer(strategy="mean").fit(TOY)  # 全データで fit（誤り）
    print("■ toy（8 行）")
    print(f"  訓練だけで fit: {float(correct.statistics_[0]):.4f}"
          f" → 検証を埋めると {values_of(correct.transform(test))}")
    print(f"  全データで fit: {float(leaked.statistics_[0]):.4f}"
          f" → 検証を埋めると {values_of(leaked.transform(test))}")
    print(f"  代入値が変わったか: {float(correct.statistics_[0]) != float(leaked.statistics_[0])}")

    # 実データ。8,000 行を 6,000 / 2,000 に分ける（行の並びは変えない）
    customers = load_customers()
    X = customers[["region"]]
    X_train, X_test = train_test_split(X, test_size=0.25, random_state=42)
    print(f"■ 実データ: 訓練 {len(X_train):,} 行 / 検証 {len(X_test):,} 行")

    imputer = SimpleImputer(strategy="most_frequent", add_indicator=True).set_output(transform="pandas")
    filled_train = imputer.fit_transform(X_train)  # fit_transform は訓練だけ
    filled_test = imputer.transform(X_test)  # 検証は transform だけ
    print(f"  訓練データで覚えた値: {imputer.statistics_[0]}")
    print(f"  全データで fit した場合の値: {SimpleImputer(strategy='most_frequent').fit(X).statistics_[0]}")

    flags = int(filled_train["missingindicator_region"].sum()) + int(
        filled_test["missingindicator_region"].sum()
    )
    print(f"  フラグの合計（訓練 + 検証）: {flags:,} 件 → 元の欠損 392 件と一致: {flags == 392}")
    print(f"  検証データに残った欠損: {int(filled_test['region'].isna().sum())} 件")
    print("■ このデータでは覚えた値が同じでも、手順を守る（差が出るデータで破綻するため）")


if __name__ == "__main__":
    main()
