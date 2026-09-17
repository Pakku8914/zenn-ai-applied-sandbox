"""セッション 8 の検証スクリプト。

「セッション8：可視化 ― 図でデータを読む」の本文・練習問題・解答に載せた数値と、
図が正しく生成できることを確認します。期待値と一致しない場合は非 0 で終了します。

図そのものの見た目は機械では判定できないので、次の 3 つを検証します。
  1. 図の元になる数値（分布・歪度・分位別の平均・構成比・月次の最大最小）
  2. 図の PNG が outputs/ に生成され、ファイルサイズが 0 より大きいこと
  3. 図の描画中にフォント欠落の警告（Glyph missing）が 1 件も出ないこと

使い方:
    docker compose exec lab python src/session08/verify_08.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import seaborn as sns

import distributions
import figure_axes
import misleading_axis
import price_rating
import q1_two_axes
import q2_rating_counts
import q3_monthly_line
import q4_band_axis
import q5_seaborn_panel
import q6_age_report
import q7_report_panel
import ratings_bar
import seaborn_quick
import trend_panel
from common import (
    AGE_BINS,
    AGE_LABELS,
    CATEGORY_ORDER,
    DATA_DIR,
    OUT_DIR,
    load_books,
    load_customers,
    load_orders,
    load_rated_reviews,
    load_reviews,
    load_valid_orders,
    monthly_amount,
)

TOLERANCE = 0.005  # 指標の許容誤差

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual}")
    if not ok:
        print(f"     期待値: {expected}")
        failures.append(label)


def check_close(label: str, actual: float, expected: float, tol: float = TOLERANCE) -> None:
    ok = abs(actual - expected) <= tol
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:.4f}")
    if not ok:
        print(f"     期待値: {expected:.4f} ± {tol}")
        failures.append(label)


def check_yen(label: str, actual: int, expected: int) -> None:
    """金額の検証。端数の丸め方の違いで 1 円ずれることがあるため 1 円まで許容する。"""
    ok = abs(actual - expected) <= 1
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:,} 円")
    if not ok:
        print(f"     期待値: {expected:,} 円 ± 1")
        failures.append(label)


missing = [
    name for name in ("books", "customers", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()
]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. 描画に使うライブラリと日本語フォントの設定
# ------------------------------------------------------------------
check("matplotlib のバージョン", matplotlib.__version__, "3.11.1")
check("seaborn のバージョン", sns.__version__, "0.13.2")
check("pandas のバージョン", pd.__version__, "3.0.5")
check("既定のフォント", list(matplotlib.rcParams["font.family"]), ["Noto Sans CJK JP"])
check("既定のバックエンド", matplotlib.get_backend().lower(), "agg")

# ------------------------------------------------------------------
# 2. 星の分布（棒グラフと件数表の元になる数値）
# ------------------------------------------------------------------
reviews = load_reviews()
check("reviews.csv の行数", len(reviews), 14467)
check("星が未入力のレビュー", int(reviews["rating"].isna().sum()), 298)

counts = reviews["rating"].value_counts().sort_index()
check("星の種類", [int(star) for star in counts.index], [1, 2, 3, 4, 5])
check("星ごとの件数", [int(number) for number in counts], [1, 38, 2558, 9325, 2247])
check("星が入っているレビューの合計", int(counts.sum()), 14169)
check_close("平均の星", float(reviews["rating"].mean()), 3.9725)
check("星 1 は 1 件しかないこと（図では見えない）", int(counts.loc[1.0]), 1)

# ------------------------------------------------------------------
# 3. レビュー本文の長さ（ヒストグラムの元になる数値）
# ------------------------------------------------------------------
length = reviews["body_length"]
check_close("body_length の平均", float(length.mean()), 83.7, tol=0.05)
check("body_length の中央値", int(length.median()), 66)
check("body_length の最大", int(length.max()), 1331)
print(f"---  星が入っている行だけの平均: {load_rated_reviews()['body_length'].mean():.1f}（参考値）")

# ------------------------------------------------------------------
# 4. 外れ値と対数変換（quantity）
# ------------------------------------------------------------------
orders = load_orders()  # 完全重複 30 件を落とした 60,031 行
quantity = orders["quantity"]
check("注文データの行数（完全重複を落とした後）", len(orders), 60031)
check_close("quantity の歪度", float(quantity.skew()), 19.4354)
check_close("log1p 変換後の歪度", float(np.log1p(quantity).skew()), 4.3653)
check("15 以上の注文", int((quantity >= 15).sum()), 118)
check("quantity の最大", int(quantity.max()), 39)
raw_quantity = pd.read_csv(Path(DATA_DIR) / "orders.csv")["quantity"]
print(f"---  重複行を落とす前（{len(raw_quantity):,} 行）の歪度: {raw_quantity.skew():.4f}（参考値）")
print(f"---  同じく log1p 変換後: {np.log1p(raw_quantity).skew():.4f}（参考値）")

# ------------------------------------------------------------------
# 5. カテゴリ別の平均価格（箱ひげ図・横棒の元になる数値）
# ------------------------------------------------------------------
books = load_books()
category_mean = books.groupby("category")["price"].mean().reindex(CATEGORY_ORDER)
check("カテゴリの並び（平均価格の安い順）", list(category_mean.index), CATEGORY_ORDER)
check(
    "カテゴリ別の平均価格（円・四捨五入）",
    [int(round(value)) for value in category_mean],
    [939, 1090, 1497, 1836, 3247],
)

# ------------------------------------------------------------------
# 6. 価格 4 分位ごとの平均の星（集約してから描く図の元になる数値）
# ------------------------------------------------------------------
rated = load_rated_reviews()
check("星が入っているレビューに書籍を結合した行数", len(rated), 14169)
rated["価格帯"] = pd.qcut(rated["price"], 4, labels=["Q1（安）", "Q2", "Q3", "Q4（高）"])
band = rated.groupby("価格帯", observed=True)["rating"].agg(["size", "mean"])
check("4 分位の数", len(band), 4)
check("4 分位の件数の合計", int(band["size"].sum()), 14169)
for label, expected in [("Q1（安）", 4.3822), ("Q2", 3.9305), ("Q3", 3.7829), ("Q4（高）", 3.7868)]:
    check_close(f"{label} の平均の星", float(band.loc[label, "mean"]), expected)
gap = abs(float(band.loc["Q3", "mean"]) - float(band.loc["Q4（高）", "mean"]))
check("Q3 と Q4 の差が 0.01 未満であること（ほぼ同じ）", gap < 0.01, True)

# ------------------------------------------------------------------
# 7. 月次売上（折れ線の元になる数値。端の月は不完全）
# ------------------------------------------------------------------
valid = load_valid_orders()
check("有効注文の件数", len(valid), 57869)
check_yen("売上合計（合計してから整数にする）", int(round(valid["amount"].sum())), 127104442)

monthly = monthly_amount()
check("月次の行数", len(monthly), 33)
check("両端を除いた完全な月の数", len(monthly.iloc[1:-1]), 31)
check("月次売上が最大の月", f"{monthly.idxmax():%Y-%m}", "2026-08")
check_yen("月次売上の最大", int(round(monthly.max())), 18281617)
check("月次売上が最小の月", f"{monthly.idxmin():%Y-%m}", "2024-01")
check_yen("月次売上の最小", int(round(monthly.min())), 64583)
check("月次の最後の月", f"{monthly.index[-1]:%Y-%m}", "2026-09")
check_yen("末尾の月（2026-09）の売上", int(round(monthly.iloc[-1])), 84496)
last_month = valid.loc[valid["ordered_at"] >= "2026-09-01", "ordered_at"]
check("末尾の月に含まれる日数", int(last_month.dt.normalize().nunique()), 1)

# ------------------------------------------------------------------
# 8. 年代別の売上構成比（誤解を招く図の題材）
# ------------------------------------------------------------------
customers = load_customers()
age_df = valid.merge(books[["book_id", "category"]], on="book_id", how="left").merge(
    customers[["customer_id", "birth_year"]], on="customer_id", how="left"
)
age_df["age"] = 2026 - age_df["birth_year"]
age_df["年代"] = pd.cut(age_df["age"], bins=AGE_BINS, labels=AGE_LABELS)
by_age = age_df.pivot_table(index="年代", columns="category", values="amount", aggfunc="sum", observed=True)
share = by_age.div(by_age.sum(axis=1), axis=0) * 100
tech = share["技術書"]
for label, value in tech.items():
    print(f"---  {label} の技術書構成比: {value:.1f}%（参考値）")
check("年代の数", len(tech), 5)
check("年代の並び", list(tech.index), AGE_LABELS)
check("技術書の構成比の最小", f"{tech.min():.1f}", "42.9")
check("技術書の構成比の最大", f"{tech.max():.1f}", "44.3")
check("どの年代も 42.9〜44.3% の範囲に収まること", bool(((tech >= 42.85) & (tech <= 44.35)).all()), True)
check("構成比の行ごとの合計が 100% になること", [round(float(v), 6) for v in share.sum(axis=1)], [100.0] * 5)

# ------------------------------------------------------------------
# 9. 図が実際に生成できること（フォント欠落の警告が 0 件であること）
# ------------------------------------------------------------------
FIGURES = [
    "s08_figure_axes.png",
    "s08_body_length_hist.png",
    "s08_quantity_log.png",
    "s08_rating_bar.png",
    "s08_price_box.png",
    "s08_price_rating.png",
    "s08_monthly_trend.png",
    "s08_seaborn_quick.png",
    "s08_misleading_axis.png",
    # 練習問題の解答（解答章に載せたスクリプトが生成する図）
    "s08_q1_two_axes.png",
    "s08_q2_rating_counts.png",
    "s08_q3_monthly_line.png",
    "s08_q4_band_axis.png",
    "s08_q5_seaborn_panel.png",
    "s08_q6_age_report.png",
    "s08_q7_report_panel.png",
]

# 前回の実行結果を消してから描き直す（「残っていただけ」を合格にしないため）
for name in FIGURES:
    (Path(OUT_DIR) / name).unlink(missing_ok=True)

modules = [
    # 本文のスクリプト
    figure_axes,
    distributions,
    ratings_bar,
    price_rating,
    trend_panel,
    misleading_axis,
    # 練習問題の解答
    q1_two_axes,
    q2_rating_counts,
    q3_monthly_line,
    q4_band_axis,
    q6_age_report,
    q7_report_panel,
    # set_theme は matplotlib の設定を全体に対して書き換えるので最後に実行する
    seaborn_quick,
    q5_seaborn_panel,
]
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):  # 各スクリプトの出力は抑制する
        for module in modules:
            module.main()
glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("図の描画で出たフォント欠落の警告の数", len(glyph_warnings), 0)

for name in FIGURES:
    path = Path(OUT_DIR) / name
    size = path.stat().st_size if path.exists() else 0
    print(f"---  {name}: {size:,} バイト")
    check(f"{name} が保存され、サイズが 0 より大きいこと", size > 0, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 8 のすべての検証に成功しました。")
