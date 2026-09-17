"""本文 1〜2 節: 手計算できる 5 件で MAE・RMSE・MAPE・R2 の性格の違いを見る。

同じ MAE でも RMSE の順位は逆になり、MAPE ではさらに順位が入れ替わります。
指標を 1 つしか見ないと結論が変わることを、いちばん小さなデータで確認します。
"""

from __future__ import annotations

import numpy as np

from common import make_toy, regression_scores


def mae_by_hand(y_true: np.ndarray, pred: np.ndarray) -> float:
    """MAE = 誤差の絶対値の平均。"""
    return float(np.mean(np.abs(y_true - pred)))


def rmse_by_hand(y_true: np.ndarray, pred: np.ndarray) -> float:
    """RMSE = 誤差を二乗して平均し、最後に平方根を取る。"""
    return float(np.sqrt(np.mean((y_true - pred) ** 2)))


def mape_by_hand(y_true: np.ndarray, pred: np.ndarray) -> float:
    """MAPE = 実測に対する誤差の割合の平均（実測が 0 に近いと使えない）。"""
    return float(np.mean(np.abs((y_true - pred) / y_true)))


def r2_by_hand(y_true: np.ndarray, pred: np.ndarray) -> float:
    """R2 = 1 - 予測との差の二乗和 / 平均との差の二乗和。"""
    ss_res = float(np.sum((y_true - pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    return 1.0 - ss_res / ss_tot


def sums_of_squares(y_true: np.ndarray, pred: np.ndarray) -> tuple[float, float]:
    """(SSres, SStot) を返す。R2 の分子と分母。"""
    ss_res = float(np.sum((y_true - pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    return ss_res, ss_tot


def verdict(value_a: float, value_b: float, smaller_is_better: bool) -> str:
    """2 つのモデルのどちらが良いかを、値つきの文にして返す。"""
    if abs(value_a - value_b) < 1e-12:
        return f"引き分け（{value_a:.4f} と {value_b:.4f}）"
    sign = "<" if smaller_is_better else ">"
    a_wins = value_a < value_b if smaller_is_better else value_a > value_b
    if a_wins:
        return f"モデルA が良い（{value_a:.4f} {sign} {value_b:.4f}）"
    return f"モデルB が良い（{value_b:.4f} {sign} {value_a:.4f}）"


def main() -> None:
    toy = make_toy()
    actual = toy["actual"].to_numpy(dtype="float64")
    model_a = toy["model_a"].to_numpy(dtype="float64")
    model_b = toy["model_b"].to_numpy(dtype="float64")

    print("■ 手計算で確かめる 5 件（実測 / モデルA / モデルB）")
    for row in toy.itertuples(index=False):
        print(f"{row.actual:4.1f} | {row.model_a:6.1f} | {row.model_b:6.1f}")
    print()

    scores_a = regression_scores(actual, model_a)
    scores_b = regression_scores(actual, model_b)
    print("■ 4 つの指標")
    print(f"モデルA  MAE {scores_a['mae']:.4f} / RMSE {scores_a['rmse']:.4f}"
          f" / MAPE {scores_a['mape']:.4f} / R2 {scores_a['r2']:+.4f}")
    print(f"モデルB  MAE {scores_b['mae']:.4f} / RMSE {scores_b['rmse']:.4f}"
          f" / MAPE {scores_b['mape']:.4f} / R2 {scores_b['r2']:+.4f}")
    print()

    print("■ 指標ごとにどちらが良いか")
    print(f"MAE : {verdict(scores_a['mae'], scores_b['mae'], smaller_is_better=True)}")
    print(f"RMSE: {verdict(scores_a['rmse'], scores_b['rmse'], smaller_is_better=True)}")
    print(f"MAPE: {verdict(scores_a['mape'], scores_b['mape'], smaller_is_better=True)}")
    print(f"R2  : {verdict(scores_a['r2'], scores_b['r2'], smaller_is_better=False)}")
    print()

    print("■ R2 の中身（分母は「平均だけを返す予測」の誤差）")
    for label, pred in [("モデルA", model_a), ("モデルB", model_b)]:
        ss_res, ss_tot = sums_of_squares(actual, pred)
        print(f"{label}: SSres {ss_res:.4f} / SStot {ss_tot:.4f}"
              f" → R2 = 1 - {ss_res:.4f}/{ss_tot:.4f} = {r2_by_hand(actual, pred):+.4f}")
    print()

    print("■ 定義どおりに計算した値と sklearn の値（モデルA）")
    pairs = [
        ("MAE ", mae_by_hand(actual, model_a), scores_a["mae"]),
        ("RMSE", rmse_by_hand(actual, model_a), scores_a["rmse"]),
        ("MAPE", mape_by_hand(actual, model_a), scores_a["mape"]),
        ("R2  ", r2_by_hand(actual, model_a), scores_a["r2"]),
    ]
    for name, by_hand, by_sklearn in pairs:
        same = abs(by_hand - by_sklearn) < 1e-12
        print(f"{name} 自作 {by_hand:.4f} / sklearn {by_sklearn:.4f} → {same}")


if __name__ == "__main__":
    main()
