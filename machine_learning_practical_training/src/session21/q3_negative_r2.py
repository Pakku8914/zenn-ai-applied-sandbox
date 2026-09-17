"""問題3 の解答: R2 が負になる例を作り、「平均予測を 0 とする相対指標」を確かめる。"""

from __future__ import annotations

import numpy as np

from common import (
    CONSTANT_GUESS,
    MEAN,
    constant_prediction,
    fit_predict_all,
    load_rated_reviews,
    print_scores,
    regression_scores,
    split_xy,
)


def sums_of_squares(y_true, pred) -> tuple[float, float]:
    """(SSres, SStot) を返す。SStot は「評価データの平均」を使った誤差。"""
    y = np.asarray(y_true, dtype="float64")
    p = np.asarray(pred, dtype="float64")
    return float(np.sum((y - p) ** 2)), float(np.sum((y - y.mean()) ** 2))


def r2_by_hand(y_true, pred) -> float:
    """R2 = 1 - SSres/SStot。"""
    ss_res, ss_tot = sums_of_squares(y_true, pred)
    return 1.0 - ss_res / ss_tot


def main() -> None:
    df = load_rated_reviews()
    y_test, preds = fit_predict_all(df)
    _, _, y_train, _ = split_xy(df)
    train_mean = float(y_train.mean())

    guess_low = constant_prediction(y_test, CONSTANT_GUESS)  # 全部 3.0
    guess_median = constant_prediction(y_test, 4.0)  # 全部 4.0（星の中央値）

    print(f"■ 定数を返すモデルの指標（評価データ {len(y_test):,} 件）")
    print_scores(MEAN, regression_scores(y_test, preds[MEAN]))
    print_scores(f"全部 {CONSTANT_GUESS:.1f}", regression_scores(y_test, guess_low))
    print_scores("全部 4.0", regression_scores(y_test, guess_median))
    print()

    ss_res, ss_tot = sums_of_squares(y_test, guess_low)
    hand = r2_by_hand(y_test, guess_low)
    sklearn_r2 = regression_scores(y_test, guess_low)["r2"]
    print(f"■ R2 を定義どおりに計算する（全部 {CONSTANT_GUESS:.1f}）")
    print(f"SSres: {ss_res:.2f}")
    print(f"SStot: {ss_tot:.2f}")
    print(f"1 - SSres/SStot: {hand:+.4f}")
    print(f"sklearn の r2_score と一致するか: {abs(hand - sklearn_r2) < 1e-10}")
    print()

    mean_ss_res, _ = sums_of_squares(y_test, preds[MEAN])
    candidates = {
        f"{CONSTANT_GUESS:.1f}": regression_scores(y_test, guess_low)["mae"],
        f"訓練データの平均 {train_mean:.2f}": regression_scores(y_test, preds[MEAN])["mae"],
        "4.0": regression_scores(y_test, guess_median)["mae"],
    }
    smallest = min(candidates, key=lambda key: candidates[key])

    print("■ 判定")
    print(f"全部 {CONSTANT_GUESS:.1f} の R2 は負か: {sklearn_r2 < 0}")
    print(f"全部 {CONSTANT_GUESS:.1f} の SSres は平均予測より大きいか: {ss_res > mean_ss_res}")
    print(f"MAE がいちばん小さい定数: {smallest}")
    print(f"その値は評価データの星の中央値（{y_test.median():.1f}）と同じか: {smallest == '4.0'}")


if __name__ == "__main__":
    main()
