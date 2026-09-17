"""横断復習① の検証スクリプト。

「横断復習①：データを読む ― セッション2〜10の総点検」の練習問題と解答に載せた
数値・挙動・図が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/review01/verify_review01.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.errors import MergeError
from scipy import stats

import q7_reconcile
import q8_fix_figure
import q9_report_fix
import q10_mini_report
from common import (
    ALPHA,
    CATEGORIES,
    DATA_DIR,
    OUT_DIR,
    REFERENCE_DATE,
    cramers_v,
    load_books,
    load_customers,
    load_orders,
    load_orders_with_customer,
    load_rated_reviews,
    load_reviews,
    load_valid_orders,
    welch_test,
)

TOLERANCE = 0.005  # 指標の許容誤差（本書共通）

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
    """金額の検証。丸め方の違いで 1 円ずれることがあるため 1 円まで許容する。"""
    ok = abs(actual - expected) <= 1
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:,} 円")
    if not ok:
        print(f"     期待値: {expected:,} 円 ± 1")
        failures.append(label)


def check_p(label: str, actual: float, expected: float | None) -> None:
    """p 値の検証。expected が None のものは「浮動小数の下限を下回る」ことだけを確認する。"""
    if expected is None:
        ok = actual < 1e-100
        want = "< 1e-100"
    else:
        ok = abs(actual - expected) <= abs(expected) * 0.1
        want = f"{expected:.3e} ± 10%"
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:.3e}")
    if not ok:
        print(f"     期待値: {want}")
        failures.append(label)


def check_coef(label: str, actual: float, expected: float, tol: float = 2e-5) -> None:
    """回帰係数の検証。桁が小さいので専用の許容誤差を使う。"""
    ok = abs(actual - expected) <= tol
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:+.6f}")
    if not ok:
        print(f"     期待値: {expected:+.6f} ± {tol}")
        failures.append(label)


missing_files = [
    name
    for name in ("books", "customers", "orders", "reviews")
    if not (Path(DATA_DIR) / f"{name}.csv").exists()
]
if missing_files:
    print(f"NG   データが未生成です: {missing_files}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

books = load_books()
customers = load_customers()
raw_orders = load_orders(dedupe=False)
orders = load_orders()
reviews = load_reviews()
valid = load_valid_orders()
rated = load_rated_reviews()

# ------------------------------------------------------------------
# 想起 1：母集団を 3 段で決める（セッション 2・4・6）
# ------------------------------------------------------------------
check("books.csv の行数", len(books), 600)
check("customers.csv の行数", len(customers), 8000)
check("orders.csv の行数（生）", len(raw_orders), 60061)
check("reviews.csv の行数", len(reviews), 14467)
check("orders の完全重複行", int(raw_orders.duplicated().sum()), 30)
check("重複を落とした注文", len(orders), 60031)
check("60,061 − 30 = 60,031", 60061 - 30, len(orders))
check("有効注文（重複・キャンセル除外）", len(valid), 57869)
canceled = orders.loc[orders["is_canceled"] == 1]
check("キャンセル注文（重複排除後）", len(canceled), 2162)
check("有効 + キャンセル = 重複排除後", len(valid) + len(canceled), len(orders))
check("キャンセル率の表示", f"{len(canceled) / len(orders):.2%}", "3.60%")
check("① 全顧客", len(customers), 8000)
check("② 注文のある顧客", int(orders["customer_id"].nunique()), 7654)
check("③ 有効注文のある顧客", int(valid["customer_id"].nunique()), 7629)
check("注文が 1 件もない顧客", len(customers) - int(orders["customer_id"].nunique()), 346)

# ------------------------------------------------------------------
# 想起 2：読み込みで型を決める（セッション 3）
# ------------------------------------------------------------------
check("文字列カラムの dtype", str(customers["region"].dtype), "str")
check("日時カラムの dtype", str(orders["ordered_at"].dtype), "datetime64[us]")
check("dtype 指定で読んだ book_id の dtype", str(books["book_id"].dtype), "str")
check("region の欠損", int(customers["region"].isna().sum()), 392)
check("region の欠損率の表示", f"{customers['region'].isna().mean():.2%}", "4.90%")
check("rating の欠損", int(reviews["rating"].isna().sum()), 298)
check("rating の欠損率の表示", f"{reviews['rating'].isna().mean():.2%}", "2.06%")
check("describe の count と行数の差", len(reviews) - int(reviews["rating"].count()), 298)
check("星が入っているレビュー", len(rated), 14169)
check("14,467 − 298 = 14,169", 14467 - 298, len(rated))
check("結合後に category が欠けた行", int(rated["category"].isna().sum()), 0)

# ------------------------------------------------------------------
# 想起 3：結合で行数が変わる（セッション 4・5）
# ------------------------------------------------------------------
naive = reviews.merge(raw_orders, on="order_id", how="inner")
safe = reviews.merge(orders, on="order_id", how="inner", validate="one_to_one")
check("レビュー × 生の注文", len(naive), 14478)
check("増えた行数", len(naive) - len(reviews), 11)
check("二重に現れた review_id", int(naive["review_id"].duplicated().sum()), 11)
check("レビュー × 重複排除後の注文", len(safe), 14467)
try:
    reviews.merge(raw_orders, on="order_id", how="inner", validate="many_to_one")
    merge_error = "（例外は出なかった）"
except MergeError as exc:
    merge_error = str(exc).splitlines()[0]  # 2 行目以降には重複キーの一覧が続く
check(
    "validate='many_to_one' のメッセージ（1 行目）",
    merge_error,
    "Merge keys are not unique in right dataset; not a many-to-one merge",
)
left_join = customers.merge(orders, on="customer_id", how="left")
check("顧客 × 注文（how='left'）", len(left_join), 60377)
check("60,031 + 346 = 60,377", len(orders) + 346, len(left_join))
check("left 結合で order_id が NaN になる行", int(left_join["order_id"].isna().sum()), 346)
flagged = orders.merge(reviews[["order_id", "rating"]], on="order_id", how="left", indicator=True)
check("indicator both", int((flagged["_merge"] == "both").sum()), 14467)
check("indicator left_only", int((flagged["_merge"] == "left_only").sum()), 45564)
check("indicator right_only", int((flagged["_merge"] == "right_only").sum()), 0)
check("both + left_only = 60,031", 14467 + 45564, len(orders))

# ------------------------------------------------------------------
# 想起 4：集約と丸め、欠けたキー（セッション 6）
# ------------------------------------------------------------------
total = float(valid["revenue"].sum())
check_yen("売上（合計してから丸める）", round(total), 127104442)
check_yen("売上（行ごとに丸めて合計）", int(valid["revenue"].round().sum()), 127104453)
check("行ごとに丸めた場合の差", int(valid["revenue"].round().sum()) - round(total), 11)
by_category = (
    valid.merge(books[["book_id", "category"]], on="book_id", how="left", validate="many_to_one")
    .groupby("category")["revenue"]
    .sum()
)
expected_revenue = {
    "技術書": 54993526,
    "ビジネス": 29804128,
    "実用書": 20639058,
    "小説": 15696007,
    "児童書": 5971724,
}
for category, expected in expected_revenue.items():
    check_yen(f"{category} の売上", round(float(by_category.loc[category])), expected)
breakdown = sum(round(float(v)) for v in by_category)
check_yen("丸めた内訳の合計", breakdown, 127104443)
check("内訳の合計と総額の差", breakdown - round(total), 1)
check(
    "売上の多い順",
    by_category.sort_values(ascending=False).index.tolist(),
    ["技術書", "ビジネス", "実用書", "小説", "児童書"],
)

joined = valid.merge(
    customers[["customer_id", "region", "channel"]],
    on="customer_id",
    how="left",
    validate="many_to_one",
)
pivot = joined.pivot_table(index="region", columns="channel", values="revenue", aggfunc="sum")
check("pivot_table の形", pivot.shape, (7, 4))
check("pivot の空のセル", int(pivot.isna().sum().sum()), 0)
top_region, top_channel = pivot.stack().idxmax()
check("最大のセルの位置", (top_region, top_channel), ("東京", "検索"))
check_yen("最大のセルの値", round(float(pivot.loc[top_region, top_channel])), 18194833)
dropped = float(joined.loc[joined["region"].isna(), "revenue"].sum())
check_yen("region 未入力の売上", round(dropped), 6492330)
check("表 + 未入力 = 総額", abs(float(pivot.to_numpy().sum()) + dropped - total) < 0.01, True)

# キーが欠損した行は既定で落ちる（小さな表で確かめる）
toy = pd.DataFrame({"region": ["東京", None, "大阪"], "revenue": [100, 200, 300]})
check("キー欠損の行は落ちる", int(toy.groupby("region")["revenue"].sum().sum()), 400)
check("dropna=False なら落ちない", int(toy.groupby("region", dropna=False)["revenue"].sum().sum()), 600)

# ------------------------------------------------------------------
# 想起 5：時系列の端と経過日数（セッション 7）
# ------------------------------------------------------------------
series = valid.set_index("ordered_at")["revenue"].sort_index()
check("最初の注文日", f"{valid['ordered_at'].min():%Y-%m-%d}", "2024-01-09")
check("最後の注文日", f"{valid['ordered_at'].max():%Y-%m-%d}", "2026-09-01")
check("日次の行数", len(series.resample("D").sum()), 967)
check("週次の行数", len(series.resample("W").sum()), 139)
monthly = series.resample("ME").sum()
check("月次の行数", len(monthly), 33)
check("期間がそろった月の数", len(monthly.iloc[1:-1]), 31)
check("月次売上が最大の月", f"{monthly.idxmax():%Y-%m}", "2026-08")
check_yen("月次売上の最大", round(float(monthly.max())), 18281617)
check("月次の先頭の月", f"{monthly.index[0]:%Y-%m}", "2024-01")
check_yen("先頭の月の売上", round(float(monthly.iloc[0])), 64583)
check("月次の末尾の月", f"{monthly.index[-1]:%Y-%m}", "2026-09")
check_yen("末尾の月の売上", round(float(monthly.iloc[-1])), 84496)
check(
    "末尾の月に含まれる日数",
    int(valid.loc[valid["ordered_at"] >= "2026-09-01", "ordered_at"].dt.normalize().nunique()),
    1,
)
by_dow = valid["ordered_at"].dt.dayofweek.value_counts().sort_index()
check("曜日の種類", len(by_dow), 7)
check("曜日別注文数の最小", int(by_dow.min()), 8106)
check("曜日別注文数の最大", int(by_dow.max()), 8496)
recency = (REFERENCE_DATE - valid.groupby("customer_id")["ordered_at"].max()).dt.days
check("経過日数を計算した顧客数", len(recency), 7629)
check_close("経過日数の平均", float(recency.mean()), 88.0, tol=0.05)
check("経過日数の中央値", int(recency.median()), 39)
active = int((recency <= 90).sum())
check("アクティブ顧客（90 日以内）", active, 5341)
check("③ を分母にした比率", f"{active / len(recency):.2%}", "70.01%")
check("① を分母にした比率", f"{active / 8000:.2%}", "66.76%")

# ------------------------------------------------------------------
# 想起 6：記述統計の落とし穴（セッション 8・9）
# ------------------------------------------------------------------
quantity = orders["quantity"]
check("quantity の母集団", len(quantity), 60031)
check_close("quantity の平均", float(quantity.mean()), 1.2741)
check("quantity の中央値", float(quantity.median()), 1.0)
check("quantity の最頻値", int(quantity.mode().iloc[0]), 1)
check_close("quantity の標準偏差", float(quantity.std()), 1.3237)
q1, q3 = float(quantity.quantile(0.25)), float(quantity.quantile(0.75))
check("Q1 と Q3", (q1, q3), (1.0, 1.0))
check("四分位範囲（IQR）", q3 - q1, 0.0)
iqr_mask = quantity > q3 + 1.5 * (q3 - q1)
check("IQR 法が外れ値とする行数", int(iqr_mask.sum()), 10914)
check("IQR 法が外れ値とする割合", f"{iqr_mask.mean():.1%}", "18.2%")
sigma_upper = float(quantity.mean() + 3 * quantity.std())
check_close("3σ 法の上限", sigma_upper, 5.2453)
check("3σ 法が外れ値とする行数", int((quantity > sigma_upper).sum()), 118)
check("3σ 法の結果が 15 冊以上と一致すること", bool((quantity > sigma_upper).equals(quantity >= 15)), True)
check_close("quantity の歪度", float(quantity.skew()), 19.4354, tol=0.01)
check_close("log1p 変換後の歪度", float(np.log1p(quantity).skew()), 4.3653, tol=0.01)

star_counts = rated["rating"].value_counts().sort_index()
check("星ごとの件数", [int(n) for n in star_counts], [1, 38, 2558, 9325, 2247])
check("星の合計", int(star_counts.sum()), 14169)
check_close("星の平均", float(rated["rating"].mean()), 3.9725)
check_close("星の標準偏差", float(rated["rating"].std()), 0.5914)

corr = rated[["rating", "body_length", "price", "pages", "published_year"]].corr()
check_close("corr(body_length, rating)", float(corr.loc["rating", "body_length"]), -0.2867)
check_close(
    "corr(body_length, rating) のスピアマン",
    float(rated["body_length"].corr(rated["rating"], method="spearman")),
    -0.2331,
)
check_close("corr(price, rating)", float(corr.loc["rating", "price"]), -0.3221)
check_close("corr(pages, rating)", float(corr.loc["rating", "pages"]), -0.2880)
check_close("corr(published_year, rating)", float(corr.loc["rating", "published_year"]), -0.0078)
check_close("corr(pages, price)", float(corr.loc["pages", "price"]), 0.9709)

single = sm.OLS(rated["rating"], sm.add_constant(rated[["pages"]])).fit()
both = sm.OLS(rated["rating"], sm.add_constant(rated[["pages", "price"]])).fit()
check_coef("単回帰の pages の係数", float(single.params["pages"]), -0.001066)
check_close("単回帰の決定係数 R2", float(single.rsquared), 0.0829)
check_coef("重回帰の pages の係数", float(both.params["pages"]), 0.001597)
check_close("重回帰の決定係数 R2", float(both.rsquared), 0.1144)
check("pages の係数の符号が反転すること", bool(single.params["pages"] < 0 < both.params["pages"]), True)

# ------------------------------------------------------------------
# 実装 9：検定の報告に使う数値（セッション 10）
# ------------------------------------------------------------------
groups = {name: rated.loc[rated["category"] == name, "rating"] for name in CATEGORIES}
expected_groups = {
    "技術書": (3527, 3.8188),
    "ビジネス": (3261, 3.8390),
    "小説": (3358, 4.3559),
    "実用書": (2858, 3.6777),
    "児童書": (1165, 4.4292),
}
for name, (n, mean) in expected_groups.items():
    check(f"{name} のレビュー件数", len(groups[name]), n)
    check_close(f"{name} の平均の星", float(groups[name].mean()), mean)
check("カテゴリ別件数の合計", sum(len(groups[name]) for name in CATEGORIES), 14169)

# 問題8 の「悪い図」の読み方（軸を切ると段違いに見えるが、実際の差は星 1 つ未満）
category_means = pd.Series({name: float(groups[name].mean()) for name in CATEGORIES})
check("平均の星が最も高いカテゴリ", category_means.idxmax(), "児童書")
check("平均の星が最も低いカテゴリ", category_means.idxmin(), "実用書")
check(
    "カテゴリ別の平均の星の最大と最小の差が星 1 つ未満であること",
    bool(category_means.max() - category_means.min() < 1.0),
    True,
)

big = welch_test(groups["技術書"], groups["小説"])
check_close("技術書 vs 小説 の t 値", big["t"], -42.5406, tol=0.01)
check_p("技術書 vs 小説 の p 値", big["p"], None)
check_close("技術書 vs 小説 の平均差", big["diff"], -0.5370)
check_close("技術書 vs 小説 の信頼区間の下限", big["ci_low"], -0.5618)
check_close("技術書 vs 小説 の信頼区間の上限", big["ci_high"], -0.5123)
check_close("技術書 vs 小説 の効果量 d", big["d"], -1.0262)
check("技術書 vs 小説 の信頼区間が 0 を含まないこと", big["ci_low"] < 0 and big["ci_high"] < 0, True)

small = welch_test(groups["小説"], groups["児童書"])
check_p("小説 vs 児童書 の p 値", small["p"], 4.022e-05)
check_close("小説 vs 児童書 の平均差", small["diff"], -0.0733)
check_close("小説 vs 児童書 の効果量 d", small["d"], -0.1390)
check("小説 vs 児童書 が有意であること", small["p"] < ALPHA, True)
check("小説 vs 児童書 の信頼区間が 0 を含むか", small["ci_low"] < 0 < small["ci_high"], False)
check("小説 vs 児童書 の効果量が 0.2 未満であること", abs(small["d"]) < 0.2, True)

none = welch_test(groups["技術書"], groups["ビジネス"])
check_p("技術書 vs ビジネス の p 値", none["p"], 0.1024)
check("技術書 vs ビジネス が有意でないこと", none["p"] >= ALPHA, True)
check("技術書 vs ビジネス の信頼区間が 0 をまたぐこと", none["ci_low"] < 0 < none["ci_high"], True)
check("技術書 vs ビジネス の平均差が星 0.1 以内であること", abs(none["diff"]) < 0.1, True)
check("技術書 vs ビジネス の効果量が 0.2 未満であること", abs(none["d"]) < 0.2, True)

pairs = list(combinations(CATEGORIES, 2))
results = {pair: welch_test(groups[pair[0]], groups[pair[1]]) for pair in pairs}
alpha_bonferroni = ALPHA / len(pairs)
check("ペアの数", len(pairs), 10)
check("Bonferroni 補正後の有意水準の表示", f"{alpha_bonferroni:.3f}", "0.005")
check("α = 0.05 で有意なペア", sum(1 for r in results.values() if r["p"] < ALPHA), 9)
check("補正後に有意なペア", sum(1 for r in results.values() if r["p"] < alpha_bonferroni), 9)
check(
    "有意でないペア",
    [f"{x} vs {y}" for (x, y), r in results.items() if r["p"] >= ALPHA],
    ["技術書 vs ビジネス"],
)
check(
    "有意だが効果量が小さいペア",
    [f"{x} vs {y}" for (x, y), r in results.items() if r["p"] < ALPHA and abs(r["d"]) < 0.2],
    ["小説 vs 児童書"],
)
check(
    "10 回検定して 1 つ以上が偶然有意になる確率の表示",
    f"{1 - (1 - ALPHA) ** len(pairs):.1%}",
    "40.1%",
)

orders_with_customer = load_orders_with_customer()
check("顧客属性を付けた注文の行数", len(orders_with_customer), 60031)
channel_table = pd.crosstab(orders_with_customer["channel"], orders_with_customer["is_canceled"])
chi2, p_channel, dof, expected_freq = stats.chi2_contingency(channel_table)
check("channel の表の形", channel_table.shape, (4, 2))
check("channel の表の合計", int(channel_table.to_numpy().sum()), 60031)
check("キャンセルされていない注文の合計", int(channel_table[0].sum()), 57869)
check_close("channel の chi2", float(chi2), 738.3593, tol=0.01)
check("channel の自由度", int(dof), 3)
check_p("channel の p 値", float(p_channel), 1.009e-159)
check_close("channel の Cramér's V", cramers_v(channel_table, float(chi2)), 0.1109)
check("期待度数が 5 未満のセル", int((expected_freq < 5).sum()), 0)

region_table = pd.crosstab(orders_with_customer["region"], orders_with_customer["is_canceled"])
chi2_region, p_region, dof_region, _ = stats.chi2_contingency(region_table)
check("region の表の形", region_table.shape, (7, 2))
check_close("region の chi2", float(chi2_region), 6.7575, tol=0.01)
check("region の自由度", int(dof_region), 6)
check_p("region の p 値", float(p_region), 0.3439)
check_close("region の Cramér's V", cramers_v(region_table, float(chi2_region)), 0.0109)
check("region の検定が有意でないこと", float(p_region) >= ALPHA, True)
check(
    "region の表から落ちた行が欠損行と一致すること",
    len(orders_with_customer) - int(region_table.to_numpy().sum()),
    int(orders_with_customer["region"].isna().sum()),
)

# ------------------------------------------------------------------
# 実装 7 〜 10：解答のスクリプトが最後まで走り、図が保存されること
# ------------------------------------------------------------------
FIGURES = ["review01_bad_vs_good.png", "review01_mini_report.png"]
for name in FIGURES:
    (Path(OUT_DIR) / name).unlink(missing_ok=True)  # 「残っていただけ」を合格にしない

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):  # 各スクリプトの出力は抑制する
        for module in (q7_reconcile, q8_fix_figure, q9_report_fix, q10_mini_report):
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
print("横断復習① のすべての検証に成功しました。")
