"""問題6: 欠損処理の 4 方針を同じ形で比較し、判断の根拠を表と図に残す。

使い方:
    docker compose exec lab python src/session11/q6_strategy_report.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.impute import SimpleImputer

from common import MISSING_LABEL, OUT_DIR, load_customers, load_orders, region_missing_revenue

FLAG_COLUMN = "region_was_missing"


def apply_strategies(customers: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """4 つの方針を「DataFrame を返す」同じ形にそろえて並べる。

    同じ形にそろえておくと、比較のコードを 1 回書くだけで済む。
    """
    mode_value = customers["region"].mode().iloc[0]
    imputer = SimpleImputer(strategy="most_frequent", add_indicator=True).set_output(transform="pandas")
    flagged = imputer.fit_transform(customers[["region"]])
    return {
        "削除": customers.dropna(subset=["region"]),
        "定数代入": customers.assign(region=customers["region"].fillna(MISSING_LABEL)),
        "最頻値代入": customers.assign(region=customers["region"].fillna(mode_value)),
        "最頻値代入＋フラグ": customers.assign(
            region=flagged["region"].to_numpy(),
            **{FLAG_COLUMN: flagged["missingindicator_region"].astype(int).to_numpy()},
        ),
    }


def save_figure(shares: dict[str, float]) -> None:
    """方針ごとの「東京の構成比」を並べ、処理の違いが生む差を 1 枚にする。"""
    fig, ax = plt.subplots(figsize=(7, 3.6))
    labels = list(shares)
    ax.bar(labels, [shares[label] * 100 for label in labels], color="#4c78a8")
    ax.axhline(shares["削除"] * 100, color="#e45756", linestyle="--", label="削除した場合の水準")
    ax.set_title("処理方法によって「東京の構成比」が変わる")
    ax.set_ylabel("東京の構成比（%）")
    ax.tick_params(axis="x", rotation=20)
    ax.legend()
    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(OUT_DIR / "s11_q6_strategies.png", dpi=120)
    plt.close(fig)


def main() -> None:
    customers = load_customers()
    orders = load_orders()
    results = apply_strategies(customers)

    print("■ 4 方針の比較")
    shares: dict[str, float] = {}
    for label, df in results.items():
        shares[label] = float((df["region"] == "東京").mean())
        n_flag = int(df[FLAG_COLUMN].sum()) if FLAG_COLUMN in df.columns else 0
        print(f"  {label}: {len(df):,} 行 / カテゴリ {df['region'].nunique()}"
              f" / 東京 {shares[label]:.2%} / フラグ列 {n_flag} 件")

    print(f"■ 削除を選んだ場合に失う売上: {round(region_missing_revenue(customers, orders)):,} 円")
    print("■ 今回の判断: region の欠損は MCAR と矛盾しない（p = 0.9416 / 0.3504 / 0.4362）ため、")
    print("  行を捨てず最頻値で代入する。ただし MNAR は検証できないのでフラグも残す。")

    save_figure(shares)
    print("■ 図を保存しました: outputs/s11_q6_strategies.png")


if __name__ == "__main__":
    main()
