"""問題1 の解答: MAE・RMSE・MAPE・R2 を定義どおりに実装し、sklearn と突き合わせる。"""

from __future__ import annotations

import numpy as np

from common import LGBM, fit_predict_all, make_toy, regression_scores

METRIC_ORDER = ["mae", "rmse", "mape", "r2"]


def metrics_by_hand(y_true, pred) -> dict[str, float]:
    """4 つの指標を numpy だけで計算する。式を見れば性格の違いが分かる。"""
    y = np.asarray(y_true, dtype="float64")
    p = np.asarray(pred, dtype="float64")
    error = y - p
    ss_res = float(np.sum(error**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return {
        "mae": float(np.mean(np.abs(error))),  # 絶対値の平均
        "rmse": float(np.sqrt(np.mean(error**2))),  # 二乗の平均の平方根
        "mape": float(np.mean(np.abs(error / y))),  # 実測に対する割合の平均
        "r2": 1.0 - ss_res / ss_tot,  # 平均予測を 0 とする相対指標
    }


def same_values(left: dict[str, float], right: dict[str, float], tol: float = 1e-12) -> bool:
    """4 指標がすべて一致するか（浮動小数点なので厳密比較はしない）。"""
    return all(abs(left[key] - right[key]) < tol for key in METRIC_ORDER)


def format_scores(scores: dict[str, float]) -> str:
    """4 指標を 1 行の文字列にする。"""
    return (
        f"MAE {scores['mae']:.4f} / RMSE {scores['rmse']:.4f}"
        f" / MAPE {scores['mape']:.4f} / R2 {scores['r2']:+.4f}"
    )


def main() -> None:
    toy = make_toy()
    actual = toy["actual"].to_numpy(dtype="float64")
    hand_a = metrics_by_hand(actual, toy["model_a"].to_numpy(dtype="float64"))
    hand_b = metrics_by_hand(actual, toy["model_b"].to_numpy(dtype="float64"))

    print("■ 練習データ 5 件の指標（自作）")
    print(f"モデルA: {format_scores(hand_a)}")
    print(f"モデルB: {format_scores(hand_b)}")
    print()

    sk_a = regression_scores(actual, toy["model_a"])
    sk_b = regression_scores(actual, toy["model_b"])
    print("■ sklearn との一致（2 モデル × 4 指標）")
    print(f"モデルA すべて一致したか: {same_values(hand_a, sk_a)}")
    print(f"モデルB すべて一致したか: {same_values(hand_b, sk_b)}")
    print()

    y_test, preds = fit_predict_all()
    pred = preds[LGBM]
    hand_real = metrics_by_hand(y_test, pred)
    sk_real = regression_scores(y_test, pred)
    print(f"■ 星の回帰（LightGBM・評価データ {len(y_test):,} 件）でも一致するか")
    print(f"自作   : {format_scores(hand_real)}")
    print(f"sklearn: {format_scores(sk_real)}")
    print(f"すべて一致したか: {same_values(hand_real, sk_real, tol=1e-10)}")
    print()

    print("■ MAE と RMSE の大小関係（RMSE が小さくなることはない）")
    for label, scores in [("モデルA", hand_a), ("モデルB", hand_b), ("LightGBM", hand_real)]:
        print(f"{label}: MAE {scores['mae']:.4f} <= RMSE {scores['rmse']:.4f} → {scores['mae'] <= scores['rmse']}")


if __name__ == "__main__":
    main()
