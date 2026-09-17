"""4 つの特徴量で星（rating）を予測する線形回帰を学習し、係数と当てはまりを読む。

使い方:
    docker compose exec lab python src/session16/fit_star_rating.py
"""

from __future__ import annotations

import numpy as np

from common import (
    FEATURES,
    coef_series,
    fit_linear,
    load_rated_reviews,
    print_coefs,
    regression_scores,
    split_xy,
)

# 「1 単位」だと小さすぎて読めないので、現実的な差に直して読みかえる
READABLE_STEPS = [("price", 1000, "価格が 1,000 円高い"), ("pages", 100, "ページ数が 100 ページ多い"), ("body_length", 100, "本文が 100 文字長い")]


def main() -> None:
    df = load_rated_reviews()
    X_train, X_test, y_train, y_test = split_xy(df)

    print("■ 母集団")
    print(f"レビュー {len(df):,} 件 / 訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件")
    print(f"使う特徴量 : {FEATURES}")

    model = fit_linear(X_train, y_train)
    coefs = coef_series(model, X_train.columns)

    print("\n■ 生スケールの係数（1 単位あたり星がいくつ動くか）")
    print_coefs(coefs, float(model.intercept_))

    print("\n■ 読みかえ（現実的な差に直す）")
    for column, step, label in READABLE_STEPS:
        print(f"{label} : 星 {coefs[column] * step:+.3f}")

    print("\n■ 評価データでの当てはまり")
    scores = regression_scores(model, X_test, y_test)
    print(f"R2 {scores['r2']:.4f} / MAE {scores['mae']:.4f} / RMSE {scores['rmse']:.4f}")

    # 平均だけを返すモデルの RMSE は、R2 と RMSE から逆算できる（= 評価データの散らばりそのもの）
    baseline_rmse = scores["rmse"] / np.sqrt(1 - scores["r2"])
    print(f"平均だけを返すモデルの RMSE（逆算）  : {baseline_rmse:.4f}")
    print(f"評価データの星の散らばり（標準偏差） : {float(y_test.std(ddof=0)):.4f}")


if __name__ == "__main__":
    main()
