"""問題6（発展）: 係数の「不安定さ」を、訓練データを 4 つに割って自分で測る。

使い方:
    docker compose exec lab python src/session16/q6_stability.py
"""

from __future__ import annotations

import numpy as np

from common import (
    CORE_FEATURES,
    add_pages_dup,
    fit_linear,
    fit_ols,
    load_rated_reviews,
    regression_scores,
    split_xy,
)

BLOCKS = 4  # 訓練データをいくつに割って係数を推定するか
DUP_FEATURES = CORE_FEATURES + ["pages_dup"]


def pages_coefs_by_block(X, y, features: list[str], blocks: int = BLOCKS) -> list[float]:
    """訓練データをブロックに割り、ブロックごとに pages の係数を推定する。"""
    coefs = []
    for index in np.array_split(np.arange(len(X)), blocks):
        result = fit_ols(X[features].iloc[index], y.iloc[index])
        coefs.append(float(result.params["pages"]))
    return coefs


def spread(values: list[float]) -> float:
    """ばらつきの物差し。ここでは「最大 − 最小」というもっとも素朴なものを使う。"""
    return max(values) - min(values)


def standard_error(X, y, features: list[str]) -> float:
    """statsmodels が計算する pages の係数の標準誤差（＝推定のぐらつき幅）。"""
    return float(fit_ols(X[features], y).bse["pages"])


def main() -> None:
    df = add_pages_dup(load_rated_reviews())
    X_train, X_test, y_train, y_test = split_xy(df, DUP_FEATURES)
    sizes = [len(index) for index in np.array_split(np.arange(len(X_train)), BLOCKS)]
    print(f"■ 訓練データ {len(X_train):,} 件を {BLOCKS} ブロックに割る（{sizes} 件）")

    plain = pages_coefs_by_block(X_train, y_train, CORE_FEATURES)
    print("\n■ pages の係数（写しなし・3 列）")
    print("ブロックごと : " + " / ".join(f"{value:+.5f}" for value in plain))
    print(f"ばらつき（最大 − 最小） : {spread(plain):.5f}")

    shaken = pages_coefs_by_block(X_train, y_train, DUP_FEATURES)
    print("\n■ pages の係数（写しあり・4 列）")
    print("ブロックごと : " + " / ".join(f"{value:+.5f}" for value in shaken))
    print(f"ばらつき（最大 − 最小） : {spread(shaken):.5f}")

    print("\n■ 判定")
    print(f"ばらつきが 10 倍以上に広がったか : {bool(spread(shaken) > spread(plain) * 10)}")
    print(f"写しありでプラスとマイナスが混ざるか : {bool(min(shaken) < 0 < max(shaken))}")
    se_plain = standard_error(X_train, y_train, CORE_FEATURES)
    se_dup = standard_error(X_train, y_train, DUP_FEATURES)
    print(f"標準誤差が 10 倍以上になるか : {bool(se_dup > se_plain * 10)}")

    plain_r2 = regression_scores(fit_linear(X_train[CORE_FEATURES], y_train), X_test[CORE_FEATURES], y_test)["r2"]
    dup_r2 = regression_scores(fit_linear(X_train[DUP_FEATURES], y_train), X_test[DUP_FEATURES], y_test)["r2"]
    print(f"評価データの R2 の差が 0.01 未満か : {bool(abs(plain_r2 - dup_r2) < 0.01)}")

    print("\n■ 判断")
    print("写しを足しても予測の精度はほとんど変わらないのに、係数はブロックを変えるだけで大きく動きます。")
    print("壊れているのはモデルではなく、「どちらの列にどれだけ配分するか」という問いそのものです。")
    print("同じ情報が二重に入っていると配分に正解が無く、手元のデータの偶然で決まってしまいます。")


if __name__ == "__main__":
    main()
