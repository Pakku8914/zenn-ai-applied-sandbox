"""中間プロジェクト①で共通して使う読み込みと図の保存（配布コード）。

同じディレクトリのスクリプトから次のように使います。

    from common import load_valid_orders, save_fig, yen

    valid = load_valid_orders()   # 有効注文 57,869 件（重複とキャンセルを除いた母集団）

中身はセッション 3 〜 8 で書いた読み込みの作法をまとめただけです。この章の
スクリプトはすべて同じディレクトリに置き、他のセッションからは import しません
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
AGE_BASE_YEAR = 2026  # 年齢の基準年。固定しないと毎年結果が変わる

# 図と表の並びは「平均価格の安い順」に固定する（セッション 8）。図ごとに並べ替えない
CATEGORY_ORDER = ["小説", "児童書", "実用書", "ビジネス", "技術書"]
# 年代の区切りと表示名はセッション 8 と同じものを使う（章ごとに区切りを変えない）
AGE_BINS = [0, 29, 39, 49, 59, 200]
AGE_LABELS = ["20代以下", "30代", "40代", "50代", "60代以上"]


def load_books() -> pd.DataFrame:
    """書籍マスタ 600 行。book_id は文字列で読む（ゼロ埋めを壊さないため）。"""
    return pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"})


def load_customers() -> pd.DataFrame:
    """顧客マスタ 8,000 行。region に 392 件の欠損がある。"""
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


def load_valid_orders() -> pd.DataFrame:
    """有効注文（重複とキャンセルを除いた 57,869 行）に、丸めない金額 revenue を足して返す。"""
    orders = load_orders()
    valid = orders.loc[orders["is_canceled"] == 0].copy()
    valid["revenue"] = valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"])
    return valid


def load_rated_reviews() -> pd.DataFrame:
    """星が入っているレビュー 14,169 行に書籍カテゴリを付けて返す（欠損 298 件を除外）。"""
    reviews = pd.read_csv(
        DATA_DIR / "reviews.csv",
        dtype={"review_id": "str", "order_id": "str", "customer_id": "str", "book_id": "str"},
        parse_dates=["reviewed_at"],
    )
    return reviews.dropna(subset=["rating"]).merge(
        load_books()[["book_id", "category"]], on="book_id", how="left", validate="many_to_one"
    )


def yen(value: float) -> str:
    """金額の表示。丸めるのは表示のときだけ（四捨五入。切り捨てない・セッション 6）。"""
    return f"{round(float(value)):,} 円"


def save_fig(fig: Figure, name: str) -> None:
    """図を outputs/ に保存し、保存先を表示してから Figure を閉じる。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / name, dpi=110, bbox_inches="tight")
    plt.close(fig)  # 閉じないと Figure が開いたまま溜まっていく
    print(f"図を保存しました: outputs/{name}")


def cohens_d(a: pd.Series, b: pd.Series) -> float:
    """効果量。平均差をプールした標準偏差で割る（件数に依存しない・セッション 10）。"""
    n1, n2 = len(a), len(b)
    v1, v2 = float(a.var(ddof=1)), float(b.var(ddof=1))
    pooled = float(np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)))
    return float((a.mean() - b.mean()) / pooled)


def welch_test(a: pd.Series, b: pd.Series) -> dict[str, float]:
    """Welch の t 検定・平均差の 95% 信頼区間・効果量をまとめて返す（セッション 10）。"""
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
        "diff": diff,
        "t": float(t_stat),
        "p": float(p_value),
        "ci_low": diff - margin,
        "ci_high": diff + margin,
        "d": cohens_d(a, b),
    }


def format_p(p: float) -> str:
    """p 値の表示。0 に丸められた値を「p = 0」と書いてしまわないための関数。"""
    if p == 0.0:
        return "0.000e+00（浮動小数の下限を下回った。報告は p < 1e-300 とする）"
    return f"{p:.3e}"
