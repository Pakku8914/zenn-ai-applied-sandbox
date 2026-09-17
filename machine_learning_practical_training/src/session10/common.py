"""セッション 10 の本文・練習問題・解答で共通して使う読み込みと検定の道具。

同じディレクトリのスクリプトから次のように使います。

    from common import ALPHA, CATEGORIES, load_reviews, ratings_by_category, welch_test

    groups = ratings_by_category(load_reviews())
    result = welch_test(groups["技術書"], groups["小説"])
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# 有意水準。「検定の前に決めておく値」であることを示すため、定数として 1 か所に書く
ALPHA = 0.05

# カテゴリの並びは固定する（実行するたびに順番が変わると、表と図が読み比べられない）
CATEGORIES = ["技術書", "ビジネス", "小説", "実用書", "児童書"]


def load_reviews() -> pd.DataFrame:
    """レビューに書籍カテゴリを付け、rating の欠損 298 件を落として返す（14,169 行）。"""
    reviews = pd.read_csv(
        DATA_DIR / "reviews.csv",
        dtype={"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["reviewed_at"],
    )
    books = pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})
    return reviews.dropna(subset=["rating"]).merge(
        books[["book_id", "category"]], on="book_id", how="left", validate="many_to_one"
    )


def load_orders() -> pd.DataFrame:
    """注文（完全重複 30 件を除いた 60,031 行）に顧客の channel と region を付けて返す。"""
    orders = pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["ordered_at"],
    ).drop_duplicates()
    customers = pd.read_csv(
        DATA_DIR / "customers.csv",
        dtype={"customer_id": "str"},
        parse_dates=["signup_date"],
    )
    return orders.merge(
        customers[["customer_id", "channel", "region"]],
        on="customer_id",
        how="left",
        validate="many_to_one",
    )


def ratings_by_category(df: pd.DataFrame) -> dict[str, pd.Series]:
    """カテゴリ名 -> rating の Series。絞り込みを 1 回で済ませ、以降は辞書から取り出す。"""
    return {name: df.loc[df["category"] == name, "rating"] for name in CATEGORIES}


def pooled_sd(a: pd.Series, b: pd.Series) -> float:
    """2 群をまとめた標準偏差（Cohen's d の分母）。

    sqrt( ((n1-1)*分散1 + (n2-1)*分散2) / (n1+n2-2) )
    """
    n1, n2 = len(a), len(b)
    v1, v2 = float(a.var(ddof=1)), float(b.var(ddof=1))
    return float(np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)))


def cohens_d(a: pd.Series, b: pd.Series) -> float:
    """効果量 Cohen's d = (平均1 - 平均2) / プールした標準偏差。"""
    return float((a.mean() - b.mean()) / pooled_sd(a, b))


def cramers_v(table: pd.DataFrame, chi2: float) -> float:
    """クロス集計表の関連の強さ。V = sqrt( chi2 / (n * (min(行数, 列数) - 1)) )。"""
    n = int(table.to_numpy().sum())
    k = min(table.shape) - 1
    return float(np.sqrt(chi2 / (n * k)))


def welch_test(a: pd.Series, b: pd.Series) -> dict[str, float]:
    """Welch の t 検定・平均差の 95% 信頼区間・効果量をまとめて返す。

    欠損値は先に落とす（残したまま渡すと結果が NaN になり、しかもエラーは出ない）。
    """
    a, b = a.dropna(), b.dropna()
    n1, n2 = len(a), len(b)
    m1, m2 = float(a.mean()), float(b.mean())
    v1, v2 = float(a.var(ddof=1)), float(b.var(ddof=1))

    # equal_var=False が Welch の t 検定（2 群の分散が等しいと仮定しない）
    t_stat, p_value = stats.ttest_ind(a, b, equal_var=False)

    se = float(np.sqrt(v1 / n1 + v2 / n2))  # 平均差の標準誤差
    # Welch–Satterthwaite の自由度。等分散を仮定しないぶん、整数にならない
    dof = se**4 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    margin = float(stats.t.ppf(1 - ALPHA / 2, dof)) * se
    diff = m1 - m2

    return {
        "n1": n1,
        "n2": n2,
        "mean1": m1,
        "mean2": m2,
        "diff": diff,
        "se": se,
        "dof": float(dof),
        "t": float(t_stat),
        "p": float(p_value),
        "ci_low": diff - margin,
        "ci_high": diff + margin,
        "d": cohens_d(a, b),
    }


def mean_ci(values: pd.Series) -> tuple[float, float, float]:
    """1 群の平均と 95% 信頼区間の幅。図のエラーバーに使う。"""
    values = values.dropna()
    n = len(values)
    mean = float(values.mean())
    se = float(values.std(ddof=1)) / np.sqrt(n)
    margin = float(stats.t.ppf(1 - ALPHA / 2, n - 1)) * se
    return mean, mean - margin, mean + margin


def format_p(p: float) -> str:
    """p 値の表示。0 に丸められた値を「p = 0」と書いてしまわないための関数。"""
    if p == 0.0:
        return "0.000e+00（浮動小数の下限を下回った。報告は p < 1e-300 とする）"
    return f"{p:.3e}"


def print_result(label: str, r: dict[str, float]) -> None:
    """検定の結果を「p 値だけにしない」形でまとめて表示する。"""
    print(f"■ {label}")
    print(f"  件数         : {r['n1']:,} 件 vs {r['n2']:,} 件")
    print(f"  平均         : {r['mean1']:.4f} vs {r['mean2']:.4f}")
    print(f"  平均差       : {r['diff']:+.4f}")
    print(f"  95% 信頼区間 : [{r['ci_low']:+.4f}, {r['ci_high']:+.4f}]")
    print(f"  t 値         : {r['t']:.4f}")
    print(f"  p 値         : {format_p(r['p'])}")
    print(f"  効果量 d     : {r['d']:+.4f}")
