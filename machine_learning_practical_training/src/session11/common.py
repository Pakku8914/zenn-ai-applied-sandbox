"""セッション 11 の本文・練習問題・解答で共通して使う読み込みと欠損の道具。

同じディレクトリのスクリプトから次のように使います。

    from common import chi2_compare, load_customers, missing_report, welch_compare

    customers = load_customers()
    missing = customers["region"].isna()
    print(missing_report(customers))
    print(chi2_compare(customers["channel"], missing)["chi2"])
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from scipy import stats

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# 有意水準。欠損の仕組みを見極める検定でも、セッション10 と同じ値を使う
ALPHA = 0.05

# 並びは固定する（実行するたびに順番が変わると、章の表や図と読み比べられない）
REGIONS = ["東京", "大阪", "愛知", "福岡", "広島", "宮城", "北海道"]
CHANNELS = ["検索", "SNS", "メルマガ", "紹介"]

# 定数代入で使うラベル。文字列を各スクリプトに散らさず 1 か所に置く
MISSING_LABEL = "不明"


def load_customers() -> pd.DataFrame:
    """顧客マスタ 8,000 行。region の欠損 392 件は落とさずそのまま残す。"""
    return pd.read_csv(
        DATA_DIR / "customers.csv",
        dtype={"customer_id": "str"},
        parse_dates=["signup_date"],
    )


def load_reviews() -> pd.DataFrame:
    """レビュー 14,467 行。rating の欠損 298 件は落とさずそのまま残す。"""
    return pd.read_csv(
        DATA_DIR / "reviews.csv",
        dtype={"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["reviewed_at"],
    )


def load_orders() -> pd.DataFrame:
    """注文。完全重複 30 件を落とした 60,031 行（本書の規約）。"""
    return pd.read_csv(
        DATA_DIR / "orders.csv",
        dtype={"order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["ordered_at"],
    ).drop_duplicates()


def missing_report(df: pd.DataFrame) -> pd.DataFrame:
    """列ごとの欠損数と欠損率のうち、欠損のある列だけを返す。

    欠損のない列まで並べると本当に見たい行が埋もれるので、最初から絞って返す。
    """
    count = df.isna().sum()
    report = pd.DataFrame({"欠損数": count, "欠損率": count / len(df)})
    return report.loc[report["欠損数"] > 0]


def order_count_per_customer(customers: pd.DataFrame, orders: pd.DataFrame) -> pd.Series:
    """顧客ごとの注文回数。母集団は重複を除いた 60,031 行。注文がない顧客は 0 とする。

    customers の行の並びに合わせて返すので、そのまま列として足せる。
    """
    counted = orders.groupby("customer_id").size()
    return counted.reindex(customers["customer_id"], fill_value=0).astype("int64")


def welch_compare(values: pd.Series, mask: pd.Series) -> dict:
    """mask が True の群（欠損群）と False の群で、数値列の平均を Welch の t 検定で比べる。

    セッション10 で作った検定をそのまま流用する。欠損値は検定の前に落とす
    （残したまま渡すと、エラーは出ないのに結果が NaN になる）。
    """
    a = values.loc[mask].dropna()
    b = values.loc[~mask].dropna()
    t_stat, p_value = stats.ttest_ind(a, b, equal_var=False)
    return {
        "n_a": int(len(a)),
        "n_b": int(len(b)),
        "mean_a": float(a.mean()),
        "mean_b": float(b.mean()),
        "diff": float(a.mean() - b.mean()),
        "t": float(t_stat),
        "p": float(p_value),
    }


def chi2_compare(category: pd.Series, mask: pd.Series) -> dict:
    """mask が True の群と False の群で、カテゴリ列の構成比をカイ二乗検定で比べる。

    返す table は行が mask（True = 欠損群）、列がカテゴリのクロス集計表。
    ratio は行ごとに合計 1 になる構成比。
    """
    table = pd.crosstab(mask, category)
    chi2, p_value, dof, _expected = stats.chi2_contingency(table)
    return {
        "table": table,
        "ratio": table.div(table.sum(axis=1), axis=0),
        "chi2": float(chi2),
        "p": float(p_value),
        "dof": int(dof),
    }


def decide(p_value: float) -> str:
    """p 値から結論の言い方を決める。断定しない書き方に固定しておく。"""
    if p_value < ALPHA:
        return f"→ p < {ALPHA} なので、2 群で分布が違う（欠損は他の列と関係している＝MAR を疑う）"
    return f"→ p >= {ALPHA} なので、違いは見つからなかった（MCAR と矛盾しない。断定はできない）"


def region_missing_revenue(customers: pd.DataFrame, orders: pd.DataFrame) -> float:
    """region が欠損した顧客の売上（円）。行を削除すると失われる金額。

    本書の売上規約どおり、重複とキャンセルを除き、行ごとには丸めない。
    """
    valid = orders.loc[orders["is_canceled"] == 0].copy()
    valid["revenue"] = valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"])
    merged = valid.merge(
        customers[["customer_id", "region"]], on="customer_id", how="left", validate="many_to_one"
    )
    return float(merged.loc[merged["region"].isna(), "revenue"].sum())
