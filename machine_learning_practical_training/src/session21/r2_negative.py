"""本文 2 節: R2 が「平均予測を 0 とする相対指標」であることを確かめる。

・R2 を定義どおり（1 - SSres/SStot）に手で計算し、r2_score と一致させる
・平均予測の R2 がほぼ 0、全部 3.0 と答えるモデルの R2 が負になることを見る
"""

from __future__ import annotations

import numpy as np

from common import (
    CONSTANT_GUESS,
    LGBM,
    MEAN,
    TARGET,
    constant_prediction,
    fit_predict_all,
    load_rated_reviews,
    print_scores,
    regression_scores,
    split_xy,
)


def r2_by_hand(y_true, pred) -> tuple[float, float, float]:
    """(SSres, SStot, R2) を返す。R2 の分母は「平均だけを返す予測」の誤差。"""
    y = np.asarray(y_true, dtype="float64")
    p = np.asarray(pred, dtype="float64")
    ss_res = float(np.sum((y - p) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return ss_res, ss_tot, 1.0 - ss_res / ss_tot


def main() -> None:
    df = load_rated_reviews()
    y_test, preds = fit_predict_all(df)
    _, _, y_train, _ = split_xy(df)

    ss_res, ss_tot, hand = r2_by_hand(y_test, preds[LGBM])
    sklearn_r2 = regression_scores(y_test, preds[LGBM])["r2"]
    print(f"■ R2 の中身（評価データ {len(y_test):,} 件・LightGBM）")
    print(f"SStot（平均との差の二乗和）: {ss_tot:.2f}")
    print(f"SSres（予測との差の二乗和）: {ss_res:.2f}")
    print(f"1 - SSres/SStot: {hand:+.4f}")
    print(f"sklearn の r2_score: {sklearn_r2:+.4f}")
    print(f"2 つが一致するか: {abs(hand - sklearn_r2) < 1e-10}")
    print()

    print("■ 定数を返すだけの 2 つのモデル")
    print_scores(MEAN, regression_scores(y_test, preds[MEAN]))
    guess = constant_prediction(y_test, CONSTANT_GUESS)
    print_scores(f"全部 {CONSTANT_GUESS:.1f}", regression_scores(y_test, guess))
    print()

    print("■ なぜ平均予測の R2 はぴったり 0 にならないのか")
    print(f"訓練データの星の平均（予測に使う定数）: {y_train.mean():.2f}")
    print(f"評価データの星の平均: {y_test.mean():.2f}")
    print(f"2 つの平均の差: {abs(y_train.mean() - y_test.mean()):.4f}")
    print(f"平均予測の R2: {regression_scores(y_test, preds[MEAN])['r2']:+.4f}")
    on_test_mean = constant_prediction(y_test, float(y_test.mean()))
    print(f"評価データの平均をそのまま返した場合の R2: {regression_scores(y_test, on_test_mean)['r2']:+.4f}")
    print()

    print("■ 判定")
    print(f"全部 {CONSTANT_GUESS:.1f} の R2 は負か: {regression_scores(y_test, guess)['r2'] < 0}")
    print(f"星の平均は {df[TARGET].mean():.4f} なので、3.0 は平均から遠い定数")


if __name__ == "__main__":
    main()
