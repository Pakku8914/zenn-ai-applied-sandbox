"""中間プロジェクト①の検証スクリプト。

「中間プロジェクト①：分析レポートを書く」「同：要件と仕様」「同：解答例」に載せた
数値・図・レポートが、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/mid01/verify_mid01.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import figures
import rating_test as rating_test_script
import report
from analysis import (
    age_segment,
    age_share,
    base_table,
    category_summary,
    cross_revenue,
    population,
    region_revenue,
)
from common import AGE_LABELS, CATEGORY_ORDER, OUT_DIR, load_rated_reviews, welch_test

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
        print(f"     期待値: {expected:,} 円 ± 1 円")
        failures.append(label)


# ------------------------------------------------------------------
# 課題1：母集団の確定
# ------------------------------------------------------------------
pop = population()
total = float(pop["total_revenue"])

check("生データの注文", int(pop["raw_orders"]), 60061)
check("重複を除いた注文", int(pop["unique_orders"]), 60031)
check("有効注文（重複・キャンセル除外）", int(pop["valid_orders"]), 57869)
check_yen("売上の総額", round(total), 127104442)
check("顧客 ① 全顧客", int(pop["all_customers"]), 8000)
check("顧客 ② 注文が 1 件以上ある顧客", int(pop["ordered_customers"]), 7654)
check("顧客 ③ 有効注文が 1 件以上ある顧客", int(pop["valid_customers"]), 7629)
check("アクティブ顧客（基準日から 90 日以内）", int(pop["active_customers"]), 5341)

base = base_table()
check("結合しても行が増えないこと", len(base), 57869)
check("年代が付かなかった行がないこと", int(base["年代"].isna().sum()), 0)
check("カテゴリが付かなかった行がないこと", int(base["category"].isna().sum()), 0)

# ------------------------------------------------------------------
# 課題2：カテゴリ別の売上・注文数・1 注文あたり平均金額
# ------------------------------------------------------------------
summary = category_summary()
check("カテゴリの並び（平均価格の安い順に固定）", summary.index.tolist(), CATEGORY_ORDER)
check(
    "売上の多い順の並び",
    summary.sort_values("revenue", ascending=False).index.tolist(),
    ["技術書", "ビジネス", "実用書", "小説", "児童書"],
)
check(
    "注文数の多い順の並び",
    summary.sort_values("orders", ascending=False).index.tolist(),
    ["技術書", "小説", "ビジネス", "実用書", "児童書"],
)
for name, revenue, orders, mean_amount, mean_price in [
    ("技術書", 54993526, 14397, "3,819.8", "3,247"),
    ("ビジネス", 29804128, 13607, "2,190.4", "1,836"),
    ("実用書", 20639058, 11548, "1,787.2", "1,497"),
    ("小説", 15696007, 13642, "1,150.6", "939"),
    ("児童書", 5971724, 4675, "1,277.4", "1,090"),
]:
    row = summary.loc[name]
    check_yen(f"{name} の売上", round(float(row["revenue"])), revenue)
    check(f"{name} の注文数", int(row["orders"]), orders)
    check(f"{name} の 1 注文あたり平均金額", f"{row['mean_amount']:,.1f}", mean_amount)
    check(f"{name} のマスタ平均価格", f"{row['mean_price']:,.0f}", mean_price)

check("内訳の注文数の合計", int(summary["orders"].sum()), 57869)
breakdown = sum(round(float(v)) for v in summary["revenue"])
check("丸めた内訳の合計", breakdown, 127104443)
check("内訳の合計と総額の差", breakdown - round(total), 1)
check("技術書が総額に占める割合", f"{summary.loc['技術書', 'revenue'] / total * 100:.1f}", "43.3")

# ------------------------------------------------------------------
# 課題3：絶対額で見たクロス集計（年代 × カテゴリ / 流入経路 × カテゴリ）
# ------------------------------------------------------------------
age_cross = cross_revenue("年代")
check("年代 × カテゴリの形", age_cross.shape, (5, 5))
check("年代の並び", [str(v) for v in age_cross.index], AGE_LABELS)
check("空のセルがないこと", int(age_cross.isna().sum().sum()), 0)
check("最大のセルの位置", tuple(age_cross.stack().idxmax()), ("30代", "技術書"))

age_top5 = age_cross.stack().sort_values(ascending=False).head(5)
check(
    "年代 × カテゴリの上位 5 セル",
    [tuple(key) for key in age_top5.index],
    [
        ("30代", "技術書"),
        ("40代", "技術書"),
        ("20代以下", "技術書"),
        ("30代", "ビジネス"),
        ("40代", "ビジネス"),
    ],
)
for (key, value), expected in zip(
    age_top5.items(), [16177927, 14894998, 13008419, 8927056, 7810802]
):
    check_yen(f"{key[0]} × {key[1]} の売上", round(float(value)), expected)

for age, expected in zip(AGE_LABELS, [13008419, 16177927, 14894998, 7736886, 3175297]):
    check_yen(f"{age} の技術書の売上", round(float(age_cross.loc[age, "技術書"])), expected)
check(
    "年代 × カテゴリの合計が総額と一致",
    abs(float(age_cross.to_numpy().sum()) - total) < 0.01,
    True,
)

channel_cross = cross_revenue("channel")
check("流入経路 × カテゴリの形", channel_cross.shape, (4, 5))
check(
    "流入経路の並び（売上の多い順）",
    channel_cross.index.tolist(),
    ["検索", "SNS", "メルマガ", "紹介"],
)
channel_top5 = channel_cross.stack().sort_values(ascending=False).head(5)
check(
    "流入経路 × カテゴリの上位 5 セル",
    [tuple(key) for key in channel_top5.index],
    [
        ("検索", "技術書"),
        ("SNS", "技術書"),
        ("検索", "ビジネス"),
        ("メルマガ", "技術書"),
        ("検索", "実用書"),
    ],
)
for (key, value), expected in zip(
    channel_top5.items(), [24480250, 13687044, 12612424, 10496671, 8901638]
):
    check_yen(f"{key[0]} × {key[1]} の売上", round(float(value)), expected)

for name, expected in [("技術書", "44.5"), ("ビジネス", "42.3"), ("実用書", "43.1")]:
    ratio = channel_cross.loc["検索", name] / summary.loc[name, "revenue"] * 100
    check(f"{name} のうち検索が占める割合", f"{ratio:.1f}", expected)

# ------------------------------------------------------------------
# 課題4：構成比（この章の結論の中心。年代でほとんど変わらない）
# ------------------------------------------------------------------
share = age_share()
check("行ごとの合計が 100% になること", [f"{v:.1f}" for v in share.sum(axis=1)], ["100.0"] * 5)
for age, expected in zip(AGE_LABELS, ["42.9", "43.0", "43.8", "43.1", "44.3"]):
    check(f"{age} の技術書の構成比", f"{share.loc[age, '技術書']:.1f}", expected)
for category, low, high in [
    ("技術書", "42.9", "44.3"),
    ("ビジネス", "22.9", "23.8"),
    ("実用書", "15.9", "16.5"),
    ("小説", "12.2", "12.9"),
    ("児童書", "4.0", "4.9"),
]:
    check(f"{category} の構成比の最小", f"{share[category].min():.1f}", low)
    check(f"{category} の構成比の最大", f"{share[category].max():.1f}", high)
check(
    "構成比の幅がいちばん広いカテゴリでも 2 ポイント未満",
    bool((share.max() - share.min()).max() < 2.0),
    True,
)

# ------------------------------------------------------------------
# 課題5：セグメントの大きさ（差があるのは人数だけ）
# ------------------------------------------------------------------
segment = age_segment()
customers = segment["customers"]
price = segment["mean_unit_price"]
for age, expected in zip(AGE_LABELS, [1859, 2275, 2024, 1059, 412]):
    check(f"{age} の顧客数", int(customers.loc[age]), expected)
check("年代別顧客数の合計", int(customers.sum()), 7629)
check("顧客数の最大 ÷ 最小", f"{customers.max() / customers.min():.2f}", "5.52")
check("顧客数が最大の年代", str(customers.idxmax()), "30代")
check("顧客数が最小の年代", str(customers.idxmin()), "60代以上")
check("年代別の平均単価の最小", f"{price.min():,.0f}", "1,841")
check("年代別の平均単価の最大", f"{price.max():,.0f}", "1,845")
check("平均単価の幅が 10 円未満", bool(price.max() - price.min() < 10), True)

# ------------------------------------------------------------------
# 課題6：地域別（region の欠損で表から消える売上）
# ------------------------------------------------------------------
by_region, missing = region_revenue()
check("地域の数", len(by_region), 7)
check("上位 3 地域の並び", by_region.index[:3].tolist(), ["東京", "大阪", "愛知"])
for name, expected in [("東京", 41662017), ("大阪", 18345823), ("愛知", 14516463)]:
    check_yen(f"{name} の売上", round(float(by_region.loc[name])), expected)
check_yen("region が未入力の顧客の売上", round(missing), 6492330)
check(
    "検算（地域別の合計 + 未入力 = 総額）",
    abs(float(by_region.sum()) + missing - total) < 0.01,
    True,
)
check("東京の割合（総額を分母）", f"{by_region.iloc[0] / total * 100:.1f}", "32.8")
check(
    "東京の割合（地域別の合計を分母）",
    f"{by_region.iloc[0] / float(by_region.sum()) * 100:.1f}",
    "34.5",
)

# ------------------------------------------------------------------
# 課題7（発展）：評価の検定。p 値だけでなく効果量と信頼区間も一致すること
# ------------------------------------------------------------------
rated = load_rated_reviews()
ratings = rating_test_script.rating_summary(rated)
check("星が入っているレビュー", int(ratings["reviews"].sum()), 14169)
check(
    "平均評価の高い順の並び",
    ratings.index.tolist(),
    ["児童書", "小説", "ビジネス", "技術書", "実用書"],
)
for name, reviews, mean_rating in [
    ("児童書", 1165, 4.4292),
    ("小説", 3358, 4.3559),
    ("ビジネス", 3261, 3.8390),
    ("技術書", 3527, 3.8188),
    ("実用書", 2858, 3.6777),
]:
    check(f"{name} のレビュー件数", int(ratings.loc[name, "reviews"]), reviews)
    check_close(f"{name} の平均評価", float(ratings.loc[name, "mean_rating"]), mean_rating)


def pair(left: str, right: str) -> dict[str, float]:
    return welch_test(
        rated.loc[rated["category"] == left, "rating"],
        rated.loc[rated["category"] == right, "rating"],
    )


tech_vs_novel = pair("技術書", "小説")
check_close("技術書 vs 小説 の平均差", tech_vs_novel["diff"], -0.5370)
check_close("技術書 vs 小説 の CI 下限", tech_vs_novel["ci_low"], -0.5618)
check_close("技術書 vs 小説 の CI 上限", tech_vs_novel["ci_high"], -0.5123)
check_close("技術書 vs 小説 の効果量 d", tech_vs_novel["d"], -1.0262)
check("技術書 vs 小説 の p 値は 0 に丸められる", tech_vs_novel["p"] == 0.0, True)

novel_vs_kids = pair("小説", "児童書")
check_close("小説 vs 児童書 の平均差", novel_vs_kids["diff"], -0.0733)
check_close("小説 vs 児童書 の CI 下限", novel_vs_kids["ci_low"], -0.1082)
check_close("小説 vs 児童書 の CI 上限", novel_vs_kids["ci_high"], -0.0384)
check_close("小説 vs 児童書 の効果量 d", novel_vs_kids["d"], -0.1390)
check("小説 vs 児童書 の p 値", f"{novel_vs_kids['p']:.3e}", "4.022e-05")

tech_vs_business = pair("技術書", "ビジネス")
check_close("技術書 vs ビジネス の平均差", tech_vs_business["diff"], -0.0202)
check_close("技術書 vs ビジネス の効果量 d", tech_vs_business["d"], -0.0396)
check("技術書 vs ビジネス の p 値", f"{tech_vs_business['p']:.3e}", "1.024e-01")
check(
    "技術書 vs ビジネス の信頼区間は 0 をまたぐ",
    bool(tech_vs_business["ci_low"] < 0 < tech_vs_business["ci_high"]),
    True,
)

# ------------------------------------------------------------------
# 課題8：図 4 枚とレポートが実際に生成されること
# ------------------------------------------------------------------
FIGURES = [
    "mid01_fig1_category.png",
    "mid01_fig2_crosstab.png",
    "mid01_fig3_age_share.png",
    "mid01_fig4_segment_size.png",
]
REPORT = "mid01_report.md"
for name in [*FIGURES, REPORT]:
    (Path(OUT_DIR) / name).unlink(missing_ok=True)  # 「前回の残り」を合格にしない

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):  # 各スクリプトの出力は抑制する
        figures.main()
        report.main()
        rating_test_script.main()
glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("図の描画で出たフォント欠落の警告の数", len(glyph_warnings), 0)

for name in FIGURES:
    path = Path(OUT_DIR) / name
    size = path.stat().st_size if path.exists() else 0
    print(f"---  {name}: {size:,} バイト")
    check(f"{name} が保存され、サイズが 0 より大きいこと", size > 0, True)

report_path = Path(OUT_DIR) / REPORT
check("レポートが書き出されていること", report_path.exists(), True)
report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
for needed in [
    "有効注文 57,869 件",
    "総額 127,104,442 円",
    "顧客 7,629 人",
    "技術書 54,993,526 円は総額の 43.3%",
    "技術書 14,397 件・小説 13,642 件",
    "30代 × 技術書 16,177,927 円",
    "42.9%〜44.3%",
    "5.52 倍",
    "1,841 円〜1,845 円",
    "6,492,330 円",
    "検算：地域別の合計 + region 未入力分 = 総額 … True",
    "相関を因果として読まない",
    *FIGURES,
]:
    check(f"レポートに「{needed}」が書かれていること", needed in report_text, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("中間プロジェクト① のすべての検証に成功しました。")
