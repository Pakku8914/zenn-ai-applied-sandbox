"""問題3: statsmodels の結果から R2・p 値・95% 信頼区間を読み取る。

使い方:
    docker compose exec lab python src/session16/q3_read_summary.py
"""

from __future__ import annotations

import pandas as pd

from common import FEATURES, fit_ols, load_rated_reviews, split_xy


def summary_table(result) -> pd.DataFrame:
    """係数・p 値・95% 信頼区間・有意かどうかを 1 つの表にまとめる。"""
    conf = result.conf_int()  # 行が列名、1 列目が下限・2 列目が上限（位置で取り出す）
    return pd.DataFrame(
        {
            "coef": [float(result.params[name]) for name in FEATURES],
            "p_value": [float(result.pvalues[name]) for name in FEATURES],
            "ci_low": [float(conf.loc[name].iloc[0]) for name in FEATURES],
            "ci_high": [float(conf.loc[name].iloc[1]) for name in FEATURES],
        },
        index=FEATURES,
    )


def crosses_zero(row) -> bool:
    """信頼区間が 0 をまたいでいるか（＝符号すら言い切れないか）。"""
    return bool(row["ci_low"] < 0 < row["ci_high"])


def main() -> None:
    df = load_rated_reviews()
    X_train, _, y_train, _ = split_xy(df)
    result = fit_ols(X_train, y_train)

    print("■ 当てはまり（訓練データ）")
    print(f"観測数 {int(result.nobs):,} 件 / R2 {result.rsquared:.4f} / 調整済み R2 {result.rsquared_adj:.4f}")
    print(f"調整済み R2 のほうが小さいか : {bool(result.rsquared_adj < result.rsquared)}")

    table = summary_table(result)
    print("\n■ 係数と p 値")
    for name, row in table.iterrows():
        p_text = f"{row['p_value']:.2e}" if row["p_value"] < 0.001 else f"{row['p_value']:.4f}"
        print(f"{name:<15}: {row['coef']:+.6f} / p 値 {p_text}")
    print(f"p < 0.05 だった列 : {list(table.index[table['p_value'] < 0.05])}")

    print("\n■ 95% 信頼区間")
    price = table.loc["price"]
    print(f"price          : [{price['ci_low']:+.6f}, {price['ci_high']:+.6f}]（幅 {price['ci_high'] - price['ci_low']:.6f}）")
    print(f"0 をまたぐ列 : {[str(name) for name, row in table.iterrows() if crosses_zero(row)]}")

    print("\n■ 判断")
    print("published_year は p 値が大きく、信頼区間が 0 をまたぐので「符号すら言い切れない」列です。")
    print("ただしこれは「刊行年は星に関係ない」の証明ではなく、このデータでは向きを決められない、")
    print("という意味にすぎません（p 値の大小は効果の大きさではありません）。")


if __name__ == "__main__":
    main()
