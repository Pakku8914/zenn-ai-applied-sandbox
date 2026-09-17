"""セッション 9 の検証スクリプト。

「セッション9：記述統計 ― 平均・分散・相関の落とし穴」の本文・練習問題・解答に
載せた数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session09/verify_09.py
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import statsmodels.api as sm

from common import (
    DATA_DIR,
    LABEL_JA,
    OUT_DIR,
    PRICE_BANDS,
    load_orders,
    load_rated_reviews,
    load_valid_orders,
    make_toy_curves,
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


def check_coef(label: str, actual: float, expected: float, tol: float = 2e-5) -> None:
    """回帰係数の検証。桁が小さいので専用の許容誤差を使う。"""
    ok = abs(actual - expected) <= tol
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:+.6f}")
    if not ok:
        print(f"     期待値: {expected:+.6f} ± {tol}")
        failures.append(label)


def check_range(label: str, actual: float, low: float, high: float) -> None:
    """p 値のように「桁だけ」を確認したい値の検証。"""
    ok = low <= actual <= high
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:.2e}")
    if not ok:
        print(f"     期待値: {low:.2e} 〜 {high:.2e}")
        failures.append(label)


missing = [name for name in ("books", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. 中心を表す 3 つの数
#    quantity の母集団は「完全重複 30 件を落とした 60,031 行」（セッション 4 の習慣）
# ------------------------------------------------------------------
orders = load_orders()
quantity = orders["quantity"]
check("quantity の行数（重複排除後）", len(quantity), 60031)
check_close("quantity の平均", float(quantity.mean()), 1.2741)
check("quantity の中央値", float(quantity.median()), 1.0)
check("quantity の最頻値", int(quantity.mode().iloc[0]), 1)
check("quantity の最小", int(quantity.min()), 1)
check("quantity の最大", int(quantity.max()), 39)
check("quantity が 4 〜 14 の行数（この範囲の値は存在しない）", int(quantity.between(4, 14).sum()), 0)
check("quantity が 15 以上の行数", int((quantity >= 15).sum()), 118)
check_close("quantity の 平均 − 中央値", float(quantity.mean() - quantity.median()), 0.2741)
check_close("quantity の歪度", float(quantity.skew()), 19.4354, tol=0.01)

reviews = load_rated_reviews()
rating = reviews["rating"]
raw_reviews = pd.read_csv(Path(DATA_DIR) / "reviews.csv")
check("reviews.csv の行数", len(raw_reviews), 14467)
check("rating の欠損数", int(raw_reviews["rating"].isna().sum()), 298)
check("星が入っているレビューの件数", len(reviews), 14169)
check("14,467 − 298 = 14,169 であること", 14467 - 298, len(reviews))
check_close("rating の平均", float(rating.mean()), 3.9725)
check("rating の中央値", float(rating.median()), 4.0)
check("rating の最頻値", float(rating.mode().iloc[0]), 4.0)
check_close("rating の 平均 − 中央値", float(rating.mean() - rating.median()), -0.0275)

# ------------------------------------------------------------------
# 2. ばらつきを表す 3 つの数
# ------------------------------------------------------------------
check_close("quantity の標準偏差", float(quantity.std()), 1.3237)
check_close("quantity の分散", float(quantity.var()), 1.7522)
check("標準偏差が分散の平方根であること（quantity）", math.isclose(math.sqrt(quantity.var()), quantity.std()), True)
check("quantity の Q1", float(quantity.quantile(0.25)), 1.0)
check("quantity の Q3", float(quantity.quantile(0.75)), 1.0)
check("quantity の四分位範囲（IQR）", float(quantity.quantile(0.75) - quantity.quantile(0.25)), 0.0)
check_close("rating の標準偏差", float(rating.std()), 0.5914)
check_close("rating の分散", float(rating.var()), 0.3498)
check("rating の Q1", float(rating.quantile(0.25)), 4.0)
check("rating の Q3", float(rating.quantile(0.75)), 4.0)
check("rating の四分位範囲（IQR）", float(rating.quantile(0.75) - rating.quantile(0.25)), 0.0)

# ------------------------------------------------------------------
# 3. 外れ値の線 ― IQR 法と 3σ 法
# ------------------------------------------------------------------
q1 = quantity.quantile(0.25)
q3 = quantity.quantile(0.75)
iqr_upper = q3 + 1.5 * (q3 - q1)
sigma_upper = quantity.mean() + 3 * quantity.std()
iqr_mask = quantity > iqr_upper
sigma_mask = quantity > sigma_upper
bulk_mask = quantity >= 15

check("IQR 法の上限", float(iqr_upper), 1.0)
check_close("3σ 法の上限", float(sigma_upper), 5.2453)
check("IQR 法が外れ値とする行数", int(iqr_mask.sum()), 10914)
check("IQR 法が外れ値とする割合", f"{iqr_mask.mean():.1%}", "18.2%")
check("3σ 法が外れ値とする行数", int(sigma_mask.sum()), 118)
check("3σ 法が外れ値とする割合", f"{sigma_mask.mean():.1%}", "0.2%")
check("3σ 法の結果がまとめ買い（15 冊以上）と一致すること", bool(sigma_mask.equals(bulk_mask)), True)

# 重複を落とさなかった場合の値も参考として出す（本文は重複排除後の 60,031 行を使っている）
raw_quantity = load_orders(dedupe=False)["quantity"]
print(
    f"---  参考（重複を落とさない生の {len(raw_quantity):,} 行）: 平均 {raw_quantity.mean():.4f} / "
    f"標準偏差 {raw_quantity.std():.4f} / IQR 法 {int((raw_quantity > 1.0).sum()):,} 行 / "
    f"15 冊以上 {int((raw_quantity >= 15).sum()):,} 行"
)

# ------------------------------------------------------------------
# 4. 相関係数
# ------------------------------------------------------------------
numeric_cols = ["rating", "body_length", "price", "pages", "published_year"]
corr = reviews[numeric_cols].corr()
check_close("corr(body_length, rating)", float(corr.loc["rating", "body_length"]), -0.2867)
check_close(
    "corr(body_length, rating) のスピアマン",
    float(reviews["body_length"].corr(reviews["rating"], method="spearman")),
    -0.2331,
)
check_close("corr(price, rating)", float(corr.loc["rating", "price"]), -0.3221)
check_close("corr(pages, rating)", float(corr.loc["rating", "pages"]), -0.2880)
check_close("corr(published_year, rating)", float(corr.loc["rating", "published_year"]), -0.0078)
check_close("corr(pages, price)", float(corr.loc["pages", "price"]), 0.9709)

books = pd.read_csv(Path(DATA_DIR) / "books.csv")
print(f"---  参考（書籍 600 冊で計算した corr(pages, price)）: {books['pages'].corr(books['price']):+.4f}")

# 数値でない列を混ぜたまま corr() を呼ぶと止まること（型名は決め打ちしない）
try:
    reviews[numeric_cols + ["category"]].corr()
    corr_raises = False
    raised = "（例外なし）"
except Exception as exc:  # noqa: BLE001 - 型が変わっても「止まる」ことだけを確認する
    corr_raises = True
    raised = type(exc).__name__
print(f"---  文字列を含む corr() で起きた例外の型: {raised}")
check("文字列を含む corr() が例外になること", corr_raises, True)

# 定義が重なっている 2 列（売上額は冊数を掛けて作っている）
valid = load_valid_orders()
check("有効注文の件数", len(valid), 57869)
check_close("corr(quantity, revenue)", float(valid["quantity"].corr(valid["amount"])), 0.7626)
all_orders = orders.copy()  # 重複排除後・キャンセルを含む 60,031 行
all_orders["amount"] = all_orders["unit_price"] * all_orders["quantity"] * (1 - all_orders["discount_rate"])
print(
    f"---  参考（キャンセルを含む {len(all_orders):,} 行での corr(quantity, revenue)）: "
    f"{all_orders['quantity'].corr(all_orders['amount']):+.4f}"
)

# ------------------------------------------------------------------
# 5. 直線以外の関係（手計算で確かめられる 7 点）
# ------------------------------------------------------------------
toy = make_toy_curves()
check("練習用データの行数", len(toy), 7)
check_close("直線のピアソン", float(toy["x"].corr(toy["line"])), 1.0)
check_close("直線のスピアマン", float(toy["x"].corr(toy["line"], method="spearman")), 1.0)
check_close("放物線のピアソン", float(toy["x"].corr(toy["parabola"])), 0.0)
check_close("放物線のスピアマン", float(toy["x"].corr(toy["parabola"], method="spearman")), 0.0)
check_close("単調な曲線のピアソン", float(toy["x"].corr(toy["cubic"])), 0.9295, tol=0.001)
check_close("単調な曲線のスピアマン", float(toy["x"].corr(toy["cubic"], method="spearman")), 1.0)

# ------------------------------------------------------------------
# 6. シンプソンのパラドックス（単回帰 → 重回帰で符号が反転する）
# ------------------------------------------------------------------
single = sm.OLS(reviews["rating"], sm.add_constant(reviews[["pages"]])).fit()
both = sm.OLS(reviews["rating"], sm.add_constant(reviews[["pages", "price"]])).fit()
check_coef("単回帰の pages の係数", float(single.params["pages"]), -0.001066)
check_range("単回帰の pages の p 値", float(single.pvalues["pages"]), 1e-270, 1e-267)
check_close("単回帰の決定係数 R2", float(single.rsquared), 0.0829)
check_coef("重回帰の pages の係数", float(both.params["pages"]), 0.001597)
check_range("重回帰の pages の p 値", float(both.pvalues["pages"]), 1e-40, 1e-37)
check_close("重回帰の決定係数 R2", float(both.rsquared), 0.1144)
check("pages の係数の符号が反転すること", bool(single.params["pages"] < 0 < both.params["pages"]), True)
check("重回帰の price の係数がマイナスであること", bool(both.params["price"] < 0), True)
check_close(
    "単回帰の R2 が corr(pages, rating) の 2 乗であること",
    float(single.rsquared),
    float(corr.loc["rating", "pages"] ** 2),
)

# 価格の 4 分位
banded = reviews.assign(price_band=pd.qcut(reviews["price"], 4, labels=PRICE_BANDS))
expected_bands = {
    "最も安い": (3577, 4.3822, 149.3),
    "やや安い": (3582, 3.9305, 222.9),
    "やや高い": (3482, 3.7829, 313.7),
    "最も高い": (3528, 3.7868, 541.6),
}
for band, (n, mean_rating, mean_pages) in expected_bands.items():
    group = banded.loc[banded["price_band"] == band]
    check(f"価格 4 分位「{band}」の件数", len(group), n)
    check_close(f"価格 4 分位「{band}」の平均の星", float(group["rating"].mean()), mean_rating)
    check_close(f"価格 4 分位「{band}」の平均ページ数", float(group["pages"].mean()), mean_pages, tol=0.1)
check("4 分位の件数の合計", sum(n for n, _, _ in expected_bands.values()), 14169)

# カテゴリ別（層別）
expected_categories = {
    "技術書": (3527, 3.8188, 3234.1, -0.2070),
    "ビジネス": (3261, 3.8390, 1831.2, -0.0485),
    "実用書": (2858, 3.6777, 1498.0, -0.0713),
    "児童書": (1165, 4.4292, 1079.7, -0.0271),
    "小説": (3358, 4.3559, 943.2, 0.0254),
}
for category, group in reviews.groupby("category"):
    n, mean_rating, mean_price, corr_pages_rating = expected_categories[category]
    check(f"{category} のレビュー件数", len(group), n)
    check_close(f"{category} の平均の星", float(group["rating"].mean()), mean_rating)
    check_close(f"{category} の平均価格", float(group["price"].mean()), mean_price, tol=0.1)
    check_close(
        f"{category} の corr(pages, rating)", float(group["pages"].corr(group["rating"])), corr_pages_rating
    )
check("カテゴリ別の件数の合計", sum(n for n, _, _, _ in expected_categories.values()), 14169)
check(
    "小説だけ相関の符号がプラスであること",
    [c for c, (_, _, _, r) in expected_categories.items() if r > 0],
    ["小説"],
)

# ------------------------------------------------------------------
# 7. 本文の「小さな例」（厚い本と薄い本の平均評価）
# ------------------------------------------------------------------
toy_simpson = pd.DataFrame(
    {
        "category": ["小説", "小説", "技術書", "技術書"],
        "thickness": ["薄い本", "厚い本", "薄い本", "厚い本"],
        "n_books": [90, 10, 10, 90],
        "mean_rating": [4.5, 4.7, 3.5, 3.7],
    }
)
for thickness, expected_mean in [("薄い本", 4.40), ("厚い本", 3.80)]:
    part = toy_simpson.loc[toy_simpson["thickness"] == thickness]
    weighted = (part["n_books"] * part["mean_rating"]).sum() / part["n_books"].sum()
    check_close(f"小さな例：{thickness}の全体平均", float(weighted), expected_mean)
check(
    "小さな例：どちらのカテゴリでも厚い本の方が高いこと",
    bool(
        toy_simpson.loc[
            (toy_simpson["category"] == "小説") & (toy_simpson["thickness"] == "厚い本"), "mean_rating"
        ].iloc[0]
        > toy_simpson.loc[
            (toy_simpson["category"] == "小説") & (toy_simpson["thickness"] == "薄い本"), "mean_rating"
        ].iloc[0]
        and toy_simpson.loc[
            (toy_simpson["category"] == "技術書") & (toy_simpson["thickness"] == "厚い本"), "mean_rating"
        ].iloc[0]
        > toy_simpson.loc[
            (toy_simpson["category"] == "技術書") & (toy_simpson["thickness"] == "薄い本"), "mean_rating"
        ].iloc[0]
    ),
    True,
)

# ------------------------------------------------------------------
# 8. 練習問題で描いてもらう 3 枚の図が、このコードで描けること
#    （解答章に載せているコードと同じ書き方で実際に保存できるかを確認する）
# ------------------------------------------------------------------
OUT_DIR.mkdir(parents=True, exist_ok=True)

fig, ax = plt.subplots(figsize=(7, 3.6))
ax.boxplot(quantity.to_numpy(), widths=0.35, flierprops={"marker": ".", "markersize": 2, "alpha": 0.15})
ax.axhline(iqr_upper, color="#d62728", linestyle="--", label=f"IQR 法の上限 {iqr_upper:.1f}")
ax.axhline(sigma_upper, color="#2ca02c", linestyle=":", label=f"3σ 法の上限 {sigma_upper:.1f}")
ax.set_title("quantity の箱ひげ図と 2 つの外れ値の線")
ax.set_ylabel("1 注文あたりの冊数")
ax.set_xticks([])
ax.legend(loc="upper right")
fig.tight_layout()
fig.savefig(OUT_DIR / "s09_outlier_lines.png", dpi=110)
plt.close(fig)

fig, ax = plt.subplots(figsize=(5.8, 4.8))
sns.heatmap(
    corr.rename(index=LABEL_JA, columns=LABEL_JA),
    annot=True,
    fmt="+.2f",
    cmap="RdBu_r",
    vmin=-1,
    vmax=1,
    square=True,
    ax=ax,
    cbar_kws={"label": "相関係数"},
)
ax.set_title("数値列どうしの相関行列")
fig.tight_layout()
fig.savefig(OUT_DIR / "s09_corr_heatmap.png", dpi=110)
plt.close(fig)

fig, axes = plt.subplots(1, 3, figsize=(10, 3.2), sharex=True)
for ax, (column, label) in zip(axes, [("line", "直線 y = 2x + 1"), ("parabola", "放物線 y = x^2"), ("cubic", "単調な曲線 y = x^3")]):
    ax.plot(toy["x"].to_numpy(), toy[column].to_numpy(), marker="o", color="#4c78a8")
    ax.set_title(f"{label}\nピアソン {toy['x'].corr(toy[column]):+.4f}")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.axhline(0, color="#cccccc", linewidth=0.8)
    ax.axvline(0, color="#cccccc", linewidth=0.8)
fig.tight_layout()
fig.savefig(OUT_DIR / "s09_nonlinear.png", dpi=110)
plt.close(fig)

fig, ax = plt.subplots(figsize=(5.6, 3.4))
ax.bar(
    ["ページ数だけ", "価格も一緒に"],
    [single.params["pages"], both.params["pages"]],
    color=["#d62728", "#4c78a8"],
)
ax.axhline(0, color="#333333", linewidth=0.8)
ax.set_ylabel("pages の係数")
ax.set_title("同じデータなのに pages の係数の符号が反転する")
fig.tight_layout()
fig.savefig(OUT_DIR / "s09_simpson.png", dpi=110)
plt.close(fig)

for name in ("s09_outlier_lines.png", "s09_corr_heatmap.png", "s09_nonlinear.png", "s09_simpson.png"):
    check(f"図 {name} が保存されていること", (OUT_DIR / name).exists(), True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 9 のすべての検証に成功しました。")
