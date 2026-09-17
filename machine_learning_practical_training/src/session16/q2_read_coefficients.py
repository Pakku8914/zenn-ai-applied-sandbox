"""問題2: 係数を「単位あたりの効果」として読み、標準化前後で順位が入れ替わることを確かめる。

使い方:
    docker compose exec lab python src/session16/q2_read_coefficients.py
"""

from __future__ import annotations

import pandas as pd

from common import (
    coef_series,
    fit_linear,
    load_rated_reviews,
    print_coefs,
    regression_scores,
    split_xy,
    standardize,
)

# 「1 単位」では小さすぎて読めないので、現実的な差に直して読みかえる
READABLE_STEPS = [
    ("price", 1000, "価格が 1,000 円高い"),
    ("pages", 100, "ページ数が 100 ページ多い"),
    ("body_length", 100, "本文が 100 文字長い"),
    ("published_year", 10, "刊行年が 10 年新しい"),
]


def readable_effects(coefs: pd.Series) -> list[tuple[str, float]]:
    """係数に「現実的な差」を掛けて、星がいくつ動くかに直す。"""
    return [(label, float(coefs[column] * step)) for column, step, label in READABLE_STEPS]


def rank_by_abs(coefs: pd.Series) -> list[str]:
    """係数の絶対値が大きい順に列名を並べる。"""
    return [str(name) for name in coefs.abs().sort_values(ascending=False).index]


def main() -> None:
    df = load_rated_reviews()
    X_train, X_test, y_train, y_test = split_xy(df)

    raw_model = fit_linear(X_train, y_train)
    raw_coefs = coef_series(raw_model, X_train.columns)
    print("■ 生スケールの係数（1 単位あたり星がいくつ動くか）")
    print_coefs(raw_coefs, float(raw_model.intercept_))

    print("\n■ 現実的な差に読みかえる")
    for label, effect in readable_effects(raw_coefs):
        print(f"{label} : 星 {effect:+.3f}")

    X_train_s, X_test_s, _ = standardize(X_train, X_test)
    std_model = fit_linear(X_train_s, y_train)
    std_coefs = coef_series(std_model, X_train_s.columns)
    print("\n■ 標準化後の係数（1 標準偏差ぶんあたり）")
    for name, value in std_coefs.items():
        print(f"{name:<15}: {value:+.4f}")
    raw_r2 = regression_scores(raw_model, X_test, y_test)["r2"]
    std_r2 = regression_scores(std_model, X_test_s, y_test)["r2"]
    print(f"決定係数は変わらない : 生スケール {raw_r2:.4f} / 標準化後 {std_r2:.4f}")

    raw_rank, std_rank = rank_by_abs(raw_coefs), rank_by_abs(std_coefs)
    print("\n■ 絶対値の大きい順")
    print(f"生スケール : {raw_rank}")
    print(f"標準化後   : {std_rank}")
    print(f"1 位が入れ替わるか   : {raw_rank[0] != std_rank[0]}")
    print(f"最下位が入れ替わるか : {raw_rank[-1] != std_rank[-1]}")

    print("\n■ 判断")
    print("生スケールの係数の大小は「単位の大小」でしかありません。円・ページ・文字・年という")
    print("違う単位の係数を並べても重要度は語れないので、比べるときは標準化後の係数を見ます。")


if __name__ == "__main__":
    main()
