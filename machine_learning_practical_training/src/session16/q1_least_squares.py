"""問題1: 最小二乗法が「いちばんマシな 1 本」を選ぶところを手で確かめる。

使い方:
    docker compose exec lab python src/session16/q1_least_squares.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

# 手計算で追える 5 点だけを使う（本文と同じデータ）
CANDIDATES = [(2.0, 0.0), (1.5, 1.5), (1.7, 0.9)]
GRID_SLOPES = [round(1.0 + 0.1 * i, 1) for i in range(15)]  # 1.0 〜 2.4


def make_toy() -> pd.DataFrame:
    """x と y が 5 組だけの練習データ。"""
    return pd.DataFrame({"x": [1, 2, 3, 4, 5], "y": [3, 4, 6, 7, 10]})


def sse_of_line(df: pd.DataFrame, slope: float, intercept: float) -> float:
    """傾きと切片を決め打ちしたときの残差二乗和。"""
    pred = intercept + slope * df["x"]
    return float(((df["y"] - pred) ** 2).sum())


def best_intercept(df: pd.DataFrame, slope: float) -> float:
    """傾きを固定したとき、SSE を最小にする切片は「y の平均 − 傾き × x の平均」。"""
    return float(df["y"].mean() - slope * df["x"].mean())


def best_slope_by_grid(df: pd.DataFrame, slopes: list[float]) -> tuple[float, float]:
    """傾きを総当たりして SSE が最小になるものを探す（最小二乗法の意味を体で覚えるため）。"""
    scores = [(sse_of_line(df, slope, best_intercept(df, slope)), slope) for slope in slopes]
    best_sse, best = min(scores)
    return best, best_sse


def slope_by_formula(df: pd.DataFrame) -> tuple[float, float, float, float]:
    """公式（Sxy / Sxx）で傾きと切片を求める。返り値は 傾き・切片・Sxy・Sxx。"""
    dx = df["x"] - df["x"].mean()
    dy = df["y"] - df["y"].mean()
    s_xy = float((dx * dy).sum())
    s_xx = float((dx * dx).sum())
    slope = s_xy / s_xx
    return slope, best_intercept(df, slope), s_xy, s_xx


def main() -> None:
    toy = make_toy()
    print("■ 5 点の練習データ")
    print(f"x : {list(toy['x'])} / y : {list(toy['y'])}")
    print(f"平均 : x {toy['x'].mean():.1f} / y {toy['y'].mean():.1f}")

    print("\n■ 候補 3 本の残差二乗和（SSE）")
    for slope, intercept in CANDIDATES:
        print(f"傾き {slope:.1f} / 切片 {intercept:.1f} : SSE {sse_of_line(toy, slope, intercept):.3f}")

    print("\n■ 傾きを 1.0 から 2.4 まで 0.1 刻みで総当たり（切片は各傾きで最適な値にする）")
    grid_slope, grid_sse = best_slope_by_grid(toy, GRID_SLOPES)
    print(f"SSE が最小になる傾き : {grid_slope:.1f} / そのときの SSE {grid_sse:.3f}")

    print("\n■ 公式で一気に解く")
    slope, intercept, s_xy, s_xx = slope_by_formula(toy)
    print(f"Sxy {s_xy:.1f} / Sxx {s_xx:.1f}")
    print(f"傾き {slope:.4f} / 切片 {intercept:.4f}")

    model = LinearRegression().fit(toy[["x"]], toy["y"])
    print(f"LinearRegression と一致するか : {bool(np.isclose(model.coef_[0], slope) and np.isclose(model.intercept_, intercept))}")
    residual = toy["y"] - model.predict(toy[["x"]])
    print(f"残差の合計が 0 か : {bool(np.isclose(residual.sum(), 0.0))}")
    print(f"決定係数 R2 : {model.score(toy[['x']], toy['y']):.4f}")
    print(f"1 - 最小 SSE / 平均線の SSE : {1 - grid_sse / sse_of_line(toy, 0.0, float(toy['y'].mean())):.4f}")


if __name__ == "__main__":
    main()
