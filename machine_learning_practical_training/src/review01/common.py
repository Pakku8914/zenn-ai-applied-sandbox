"""横断復習①（セッション 2 〜 10）の練習問題と解答で共通して使う道具。

これまでの章で少しずつ身につけた「読み込みの作法」と「統計の道具」を 1 か所にまとめたものです。

    from common import load_valid_orders, welch_test

    valid = load_valid_orders()   # 有効注文 57,869 件（重複とキャンセルを除いた母集団）

この章のスクリプトはすべて同じディレクトリに置き、他のセッションからは import しません
（読者はその章のファイルだけを作って実行するため）。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 画面のないコンテナで図を PNG として保存するための設定
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

ALPHA = 0.05  # 有意水準は検定の前に決めておく（セッション 10）
REFERENCE_DATE = pd.Timestamp("2026-09-01")  # 「今日」を固定する（セッション 7）

# 検定のペアを列挙する順番。並びを変えると平均差の符号が反転する（セッション 10）
CATEGORIES = ["技術書", "ビジネス", "小説", "実用書", "児童書"]
# 図の並びは「平均価格の安い順」に固定する（セッション 8）
CATEGORY_ORDER = ["小説", "児童書", "実用書", "ビジネス", "技術書"]


def load_books() -> pd.DataFrame:
    """書籍マスタ 600 行。book_id は文字列で読む（ゼロ埋めを壊さないため）。"""
    return pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})


def load_customers() -> pd.DataFrame:
    """顧客マスタ 8,000 行。region に欠損がある。"""
    return pd.read_csv(
        DATA_DIR / "customers.csv", dtype={"customer_id": "str"}, parse_dates=["signup_date"]
    )


def load_orders(dedupe: bool = True) -> pd.DataFrame:
    """注文。既定では完全重複 30 件を落として 60,031 行にする（セッション 4 の規約）。"""
    orders = pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["ordered_at"],
    )
    return orders.drop_duplicates() if dedupe else orders


def load_reviews() -> pd.DataFrame:
    """レビュー 14,467 行。rating に欠損がある。"""
    return pd.read_csv(
        DATA_DIR / "reviews.csv",
        dtype={"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["reviewed_at"],
    )


def load_valid_orders() -> pd.DataFrame:
    """有効注文（重複とキャンセルを除いた 57,869 行）に、丸めない金額 revenue を足して返す。"""
    orders = load_orders()
    valid = orders.loc[orders["is_canceled"] == 0].copy()
    valid["revenue"] = valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"])
    return valid


def load_orders_with_customer() -> pd.DataFrame:
    """注文 60,031 行に顧客の channel と region を付ける（多対一なので行は増えない）。"""
    return load_orders().merge(
        load_customers()[["customer_id", "channel", "region"]],
        on="customer_id",
        how="left",
        validate="many_to_one",
    )


def load_rated_reviews() -> pd.DataFrame:
    """星が入っているレビュー 14,169 行に書籍マスタを結合して返す。"""
    return (
        load_reviews()
        .dropna(subset=["rating"])
        .merge(load_books(), on="book_id", how="left", validate="many_to_one")
    )


def show_rows(label: str, before: int, after: int) -> None:
    """行数が前後でどう変わったかを 1 行で表示する（検算の習慣・セッション 5）。"""
    diff = after - before
    sign = "±0" if diff == 0 else f"{diff:+,}"
    print(f"{label}: {before:,} 行 → {after:,} 行 ({sign})")


def yen(value: float) -> str:
    """金額の表示。丸めるのは表示するときだけ（四捨五入。切り捨てない・セッション 6）。"""
    return f"{round(float(value)):,} 円"


def pooled_sd(a: pd.Series, b: pd.Series) -> float:
    """2 群をまとめた標準偏差（Cohen's d の分母）。"""
    n1, n2 = len(a), len(b)
    v1, v2 = float(a.var(ddof=1)), float(b.var(ddof=1))
    return float(np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)))


def cohens_d(a: pd.Series, b: pd.Series) -> float:
    """効果量。平均差をプールした標準偏差で割る（件数に依存しない）。"""
    return float((a.mean() - b.mean()) / pooled_sd(a, b))


def welch_test(a: pd.Series, b: pd.Series) -> dict[str, float]:
    """Welch の t 検定・平均差の 95% 信頼区間・効果量をまとめて返す。"""
    a, b = a.dropna(), b.dropna()  # 欠損を残すと結果が NaN になり、しかもエラーは出ない
    n1, n2 = len(a), len(b)
    v1, v2 = float(a.var(ddof=1)), float(b.var(ddof=1))
    t_stat, p_value = stats.ttest_ind(a, b, equal_var=False)  # equal_var=False が Welch
    se = float(np.sqrt(v1 / n1 + v2 / n2))
    dof = se**4 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    diff = float(a.mean() - b.mean())
    margin = float(stats.t.ppf(1 - ALPHA / 2, dof)) * se
    return {
        "n1": n1,
        "n2": n2,
        "mean1": float(a.mean()),
        "mean2": float(b.mean()),
        "diff": diff,
        "t": float(t_stat),
        "p": float(p_value),
        "ci_low": diff - margin,
        "ci_high": diff + margin,
        "d": cohens_d(a, b),
    }


def mean_ci(values: pd.Series) -> tuple[float, float, float]:
    """1 群の平均と 95% 信頼区間。図のエラーバーに使う。"""
    values = values.dropna()
    mean = float(values.mean())
    se = float(values.std(ddof=1)) / np.sqrt(len(values))
    margin = float(stats.t.ppf(1 - ALPHA / 2, len(values) - 1)) * se
    return mean, mean - margin, mean + margin


def cramers_v(table: pd.DataFrame, chi2: float) -> float:
    """クロス集計表の関連の強さ。V = sqrt( chi2 / (n * (min(行数, 列数) - 1)) )。"""
    n = int(table.to_numpy().sum())
    return float(np.sqrt(chi2 / (n * (min(table.shape) - 1))))


def format_p(p: float) -> str:
    """p 値の表示。0 に丸められた値を「p = 0」と書いてしまわないための関数。"""
    if p == 0.0:
        return "0.000e+00（浮動小数の下限を下回った。報告は p < 1e-300 とする）"
    return f"{p:.3e}"


def save_fig(fig: Figure, name: str) -> None:
    """図を outputs/ に保存し、保存先を表示してから Figure を閉じる。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / name, dpi=110, bbox_inches="tight")
    plt.close(fig)  # 閉じないと Figure が開いたまま溜まっていく
    print(f"図を保存しました: outputs/{name}")
