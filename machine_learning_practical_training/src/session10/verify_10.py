"""セッション 10 の検証スクリプト。

「セッション10：統計的仮説検定 ― p 値と効果量」の本文・練習問題・解答に載せた
数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session10/verify_10.py
"""

from __future__ import annotations

from itertools import combinations
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from common import (
    ALPHA,
    CATEGORIES,
    DATA_DIR,
    cramers_v,
    load_orders,
    load_reviews,
    mean_ci,
    pooled_sd,
    ratings_by_category,
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


def check_p(label: str, actual: float, expected: float | None) -> None:
    """p 値の検証。

    expected が None のものは、浮動小数の下限を下回って 0 と表示されるため、
    厳密比較をせず「p < 1e-100 である」ことだけを確認する。
    それ以外は指数部まで含めた相対誤差 10% で比較する。
    """
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


missing = [name for name in ("books", "customers", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. p 値の定義（コイン投げ）
# ------------------------------------------------------------------
check("10 回投げたときの出方の総数", 2**10, 1024)
check("表が 8 回以上になる出方", sum(comb(10, k) for k in range(8, 11)), 56)
check_close("表が 8 回以上になる確率", float(stats.binom.sf(7, 10, 0.5)), 0.0547)
check_close("表が 9 回以上になる確率", float(stats.binom.sf(8, 10, 0.5)), 0.0107)
check_close("表が 10 回になる確率", float(stats.binom.pmf(10, 10, 0.5)), 0.0010)
check_close("両側検定の p 値", float(stats.binomtest(8, 10, 0.5, alternative="two-sided").pvalue), 0.1094)
check_close("片側検定の p 値", float(stats.binomtest(8, 10, 0.5, alternative="greater").pvalue), 0.0547)

# 練習問題 1（12 回投げて 10 回表）
check("12 回投げたときの出方の総数", 2**12, 4096)
check("表が 10 回以上になる出方", sum(comb(12, k) for k in range(10, 13)), 79)
check_close("表が 10 回以上になる確率", float(stats.binom.sf(9, 12, 0.5)), 0.0193)
check_close("12 回・10 回表の両側 p 値", float(stats.binomtest(10, 12, 0.5, alternative="two-sided").pvalue), 0.0386)
# 境界を 1 つ間違えた場合（sf(10) = 11 回以上）の値。解答の解説で触れている
check_close("境界を誤った場合の確率", float(stats.binom.sf(10, 12, 0.5)), 0.0032)

# ------------------------------------------------------------------
# 2. カテゴリ別の rating（件数・平均・標準偏差）
# ------------------------------------------------------------------
reviews_all = pd.read_csv(DATA_DIR / "reviews.csv", dtype={"book_id": "str"})
check("reviews.csv の行数", len(reviews_all), 14467)
check("rating の欠損数", int(reviews_all["rating"].isna().sum()), 298)

df = load_reviews()
check("欠損を除いたレビュー件数", len(df), 14169)
check("欠損を除いた件数が 14,467 - 298 と一致すること", len(df), 14467 - 298)
check("カテゴリが欠けた行の数", int(df["category"].isna().sum()), 0)

groups = ratings_by_category(df)
expected_stats = {
    "技術書": (3527, 3.8188, 0.5178),
    "小説": (3358, 4.3559, 0.5291),
    "ビジネス": (3261, 3.8390, 0.4998),
    "実用書": (2858, 3.6777, 0.5332),
    "児童書": (1165, 4.4292, 0.5222),
}
for name, (n, mean, sd) in expected_stats.items():
    check(f"{name} のレビュー件数", len(groups[name]), n)
    check_close(f"{name} の rating の平均", float(groups[name].mean()), mean)
    check_close(f"{name} の rating の標準偏差", float(groups[name].std(ddof=1)), sd)
check("件数の合計", sum(len(groups[name]) for name in CATEGORIES), 14169)
check(
    "平均の高い順の並び",
    sorted(groups, key=lambda c: -groups[c].mean()),
    ["児童書", "小説", "ビジネス", "技術書", "実用書"],
)

# ------------------------------------------------------------------
# 3. Welch の t 検定（技術書 vs 小説）— 大きな差
# ------------------------------------------------------------------
big = welch_test(groups["技術書"], groups["小説"])
check("技術書の件数", big["n1"], 3527)
check("小説の件数", big["n2"], 3358)
check_close("技術書 vs 小説 の t 値", big["t"], -42.5406, tol=0.01)
check_p("技術書 vs 小説 の p 値", big["p"], None)
check_close("技術書 vs 小説 の平均差", big["diff"], -0.5370)
check_close("技術書 vs 小説 の信頼区間の下限", big["ci_low"], -0.5618)
check_close("技術書 vs 小説 の信頼区間の上限", big["ci_high"], -0.5123)
check_close("技術書 vs 小説 の効果量 d", big["d"], -1.0262)
check("信頼区間が 0 を含まないこと", big["ci_low"] < 0 and big["ci_high"] < 0, True)

# ------------------------------------------------------------------
# 4. 有意だが小さい差（小説 vs 児童書）と有意でない差（技術書 vs ビジネス）
# ------------------------------------------------------------------
small = welch_test(groups["小説"], groups["児童書"])
check_close("小説 vs 児童書 の t 値", small["t"], -4.1152, tol=0.01)
check_p("小説 vs 児童書 の p 値", small["p"], 4.022e-05)
check_close("小説 vs 児童書 の平均差", small["diff"], -0.0733)
check_close("小説 vs 児童書 の信頼区間の下限", small["ci_low"], -0.1082)
check_close("小説 vs 児童書 の信頼区間の上限", small["ci_high"], -0.0384)
check_close("小説 vs 児童書 の効果量 d", small["d"], -0.1390)
check("有意（p < 0.05）であること", small["p"] < ALPHA, True)
check("効果量が 0.2 未満であること", abs(small["d"]) < 0.2, True)

# 練習問題 2（小説 vs 実用書）で本文に書いた性質
novel_vs_practical = welch_test(groups["小説"], groups["実用書"])
check_close("小説 vs 実用書 の平均差", novel_vs_practical["diff"], 0.6781)
check_close("小説 vs 実用書 の効果量 d", novel_vs_practical["d"], 1.2771)
check_p("小説 vs 実用書 の p 値", novel_vs_practical["p"], None)
check("小説 vs 実用書 の t 値が 40 を超えること", novel_vs_practical["t"] > 40, True)
check(
    "小説 vs 実用書 の信頼区間が両端とも正であること",
    novel_vs_practical["ci_low"] > 0 and novel_vs_practical["ci_high"] > 0,
    True,
)

none = welch_test(groups["技術書"], groups["ビジネス"])
check_p("技術書 vs ビジネス の p 値", none["p"], 0.1024)
check_close("技術書 vs ビジネス の平均差", none["diff"], -0.0202)
check_close("技術書 vs ビジネス の効果量 d", none["d"], -0.0396)
check("有意でないこと", none["p"] >= ALPHA, True)
check("信頼区間が 0 をまたぐこと", none["ci_low"] < 0 < none["ci_high"], True)

# 1 群ごとの 95% 信頼区間の重なり（本文の図 s10_category_rating.png の読み取り）
ci = {name: mean_ci(groups[name]) for name in CATEGORIES}


def overlaps(a: tuple[float, float, float], b: tuple[float, float, float]) -> bool:
    return a[1] <= b[2] and b[1] <= a[2]


check("技術書とビジネスの信頼区間が重なること", overlaps(ci["技術書"], ci["ビジネス"]), True)
check("小説と児童書の信頼区間が重ならないこと", overlaps(ci["小説"], ci["児童書"]), False)

# ------------------------------------------------------------------
# 5. 欠損を残したままの検定（エラーにならず NaN になる）
# ------------------------------------------------------------------
a = pd.Series([4.0, 5.0, np.nan, 4.0])
b = pd.Series([3.0, 4.0, 5.0, 3.0])
propagate = stats.ttest_ind(a, b, equal_var=False, nan_policy="propagate")
check("欠損を残すと t 値が NaN になること", bool(np.isnan(propagate.statistic)), True)
omit = stats.ttest_ind(a, b, equal_var=False, nan_policy="omit")
check("nan_policy='omit' なら計算できること", bool(np.isfinite(omit.statistic)), True)

# ------------------------------------------------------------------
# 6. 全 10 ペアと Bonferroni 補正
# ------------------------------------------------------------------
pairs = list(combinations(CATEGORIES, 2))
check("ペアの数", len(pairs), 10)
expected_pairs = {
    ("技術書", "ビジネス"): (-0.0202, 0.1024, -0.0396),
    ("技術書", "小説"): (-0.5370, None, -1.0262),
    ("技術書", "実用書"): (0.1411, 2.975e-26, 0.2689),
    ("技術書", "児童書"): (-0.6104, 4.908e-206, -1.1763),
    ("ビジネス", "小説"): (-0.5169, None, -1.0038),
    ("ビジネス", "実用書"): (0.1613, 1.4e-33, 0.3127),
    ("ビジネス", "児童書"): (-0.5902, 4.586e-195, -1.1668),
    ("小説", "実用書"): (0.6781, None, 1.2771),
    ("小説", "児童書"): (-0.0733, 4.022e-05, -0.1390),
    ("実用書", "児童書"): (-0.7514, 5.3e-275, -1.4177),
}
check("期待値を用意したペアの数", len(expected_pairs), 10)
results = {(x, y): welch_test(groups[x], groups[y]) for x, y in pairs}
for (x, y), (diff, p, d) in expected_pairs.items():
    r = results[(x, y)]
    check_close(f"{x} vs {y} の平均差", r["diff"], diff)
    check_p(f"{x} vs {y} の p 値", r["p"], p)
    check_close(f"{x} vs {y} の効果量 d", r["d"], d)

alpha_bonferroni = ALPHA / len(pairs)
check("Bonferroni 補正後の有意水準", round(alpha_bonferroni, 6), 0.005)
before = sum(1 for r in results.values() if r["p"] < ALPHA)
after = sum(1 for r in results.values() if r["p"] < alpha_bonferroni)
check("α = 0.05 で有意なペアの数", before, 9)
check("Bonferroni 補正後に有意なペアの数", after, 9)
check("補正で結論が変わらないこと", before == after, True)
check(
    "有意でない唯一のペア",
    [f"{x} vs {y}" for (x, y), r in results.items() if r["p"] >= ALPHA],
    ["技術書 vs ビジネス"],
)
check_close("10 回検定したときに 1 つ以上が偶然有意になる確率", 1 - (1 - ALPHA) ** 10, 0.4013)

# ------------------------------------------------------------------
# 7. カイ二乗検定（channel × is_canceled）
# ------------------------------------------------------------------
orders = load_orders()
check("重複を除いた注文の行数", len(orders), 60031)
table = pd.crosstab(orders["channel"], orders["is_canceled"])
check("クロス集計表の形", table.shape, (4, 2))
check("行の並び", list(table.index), ["SNS", "メルマガ", "検索", "紹介"])
expected_cells = {
    "SNS": (15463, 1153, "6.94%"),
    "メルマガ": (10687, 263, "2.40%"),
    "検索": (24933, 573, "2.25%"),
    "紹介": (6786, 173, "2.49%"),
}
for channel, (valid, canceled, rate) in expected_cells.items():
    check(f"{channel} の有効注文", int(table.loc[channel, 0]), valid)
    check(f"{channel} のキャンセル", int(table.loc[channel, 1]), canceled)
    check(f"{channel} のキャンセル率", f"{canceled / (valid + canceled):.2%}", rate)
check("クロス集計表の合計", int(table.to_numpy().sum()), 60031)
check("キャンセルされていない注文の合計", int(table[0].sum()), 57869)

chi2, p_chi2, dof, expected_freq = stats.chi2_contingency(table)
check_close("chi2", float(chi2), 738.3593, tol=0.01)
check("自由度", int(dof), 3)
check_p("カイ二乗検定の p 値", float(p_chi2), 1.009e-159)
check_close("Cramér's V", cramers_v(table, float(chi2)), 0.1109)
check("Cramér's V が 0.2 未満（関連は弱い）であること", cramers_v(table, float(chi2)) < 0.2, True)
check_close("期待度数の最小", float(expected_freq.min()), 250.6, tol=0.5)
check("期待度数が 5 未満のセルが無いこと", int((expected_freq < 5).sum()), 0)
check_close("SNS のキャンセルの期待度数", float(expected_freq[0][1]), 598.4, tol=0.5)

# ------------------------------------------------------------------
# 8. 有意にならないカイ二乗検定（region × is_canceled）
# ------------------------------------------------------------------
region_table = pd.crosstab(orders["region"], orders["is_canceled"])
check("region の表の形", region_table.shape, (7, 2))
chi2_r, p_r, dof_r, expected_r = stats.chi2_contingency(region_table)
check_close("region の chi2", float(chi2_r), 6.7575, tol=0.01)
check("region の自由度", int(dof_r), 6)
check_p("region の p 値", float(p_r), 0.3439)
check_close("region の Cramér's V", cramers_v(region_table, float(chi2_r)), 0.0109)
check("region の検定が有意でないこと", float(p_r) >= ALPHA, True)
used = int(region_table.to_numpy().sum())
check("欠損のため行数が 60,031 件より少なくなること", used < len(orders), True)
check("除かれた行が region の欠損行と一致すること", used, int(orders["region"].notna().sum()))

# 練習問題 5：欠損を「不明」として 1 カテゴリにすると、行が捨てられない
filled_table = pd.crosstab(orders["region"].fillna("不明"), orders["is_canceled"])
check("欠損を埋めた表の形", filled_table.shape, (8, 2))
check("欠損を埋めた表の合計", int(filled_table.to_numpy().sum()), 60031)

# ------------------------------------------------------------------
# 9. サンプルサイズと p 値（効果量は変わらない）
# ------------------------------------------------------------------
s_pooled = pooled_sd(groups["小説"], groups["児童書"])
diff_fixed = float(groups["小説"].mean() - groups["児童書"].mean())
check_close("小説と児童書のプールした標準偏差", s_pooled, 0.5274)
sizes = (50, 100, 200, 500, 1000, 2000)
p_values: list[float] = []
flags: list[bool] = []
for n in sizes:
    se = s_pooled * np.sqrt(2 / n)
    t_stat = diff_fixed / se
    p_value = float(2 * stats.t.sf(abs(t_stat), 2 * n - 2))
    p_values.append(p_value)
    flags.append(p_value < ALPHA)
    check_close(f"n={n} のときの効果量 d", diff_fixed / s_pooled, -0.1390)
check("有意判定の並び（n が小さいほど有意にならない）", flags, [False, False, False, True, True, True])
check(
    "n が増えるほど p 値が小さくなること",
    all(p_values[i] > p_values[i + 1] for i in range(len(p_values) - 1)),
    True,
)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 10 のすべての検証に成功しました。")
