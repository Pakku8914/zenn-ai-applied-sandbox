"""セッション 27 の検証スクリプト。

「セッション27：教師なし学習 ― クラスタリングと次元削減」の本文・練習問題・解答に
載せた数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session27/verify_27.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import build_rfm
import choose_k
import kmeans_basics
import pca_axes
import q1_rfm_table
import q2_kmeans_profile
import q3_scaling_effect
import q4_choose_k
import q5_pca_axes
import q6_segment_decision
import scaling_matters
import segment_report
from common import DATA_DIR, FEATURES, K_ALT, K_MAIN, OUT_DIR

TOLERANCE = 0.005   # 指標の許容誤差（本書共通。シルエット係数・寄与率・主成分の係数）
DAYS = 0.15         # 日数の平均（本文は「約 88 日」。小数第 1 位は丸めの取り方で動く）
COUNT_TOL = 0.1     # profile の recency・frequency（本文には小数第 1 位まで載せている）
YEN = 2.0           # profile の monetary（本文には円単位で載せている）
RELATIVE = 0.01     # inertia の相対許容誤差

# 本文に載せた実測値（ここを唯一の出典にする）
VALID_ORDERS = 57869
REVENUE = 127104442
CUSTOMERS = {"all": 8000, "ordered": 7654, "valid": 7629}
FREQUENCY_MEAN = VALID_ORDERS / CUSTOMERS["valid"]   # 7.5847...（本文では「約 7.6 回」）
MONETARY_MEAN = REVENUE / CUSTOMERS["valid"]         # 16,660.7 円（本文では 16,661 円）
ACTIVE = 5341

SWEEP = {  # k: (inertia, シルエット係数)
    2: (12966.8, 0.4648),
    3: (7992.2, 0.4882),
    4: (5723.2, 0.4214),
    5: (4657.8, 0.4086),
    6: (3757.8, 0.3973),
}
PROFILE = {  # クラスタ番号: (人数, recency, frequency, monetary)
    0: (2472, 39.7, 10.4, 22668.0),
    1: (3610, 69.6, 4.1, 8445.0),
    2: (772, 25.6, 19.8, 46805.0),
    3: (775, 390.6, 2.6, 5740.0),
}
SCALED_COUNTS = [2472, 3610, 772, 775]
RAW_COUNTS = [3739, 1106, 198, 2586]
NAMES = {0: "常連顧客", 1: "一般顧客", 2: "優良顧客", 3: "離脱顧客"}
PCA_RATIO = [0.7088, 0.2607, 0.0305]
PCA_CUMULATIVE = [0.7088, 0.9695, 1.0000]
PC1 = {"recency": -0.4034, "frequency": 0.6509, "monetary": 0.6431}
PC2 = {"recency": 0.9143, "frequency": 0.2590, "monetary": 0.3114}
CUSTOMER_SHARE = {0: 0.324, 1: 0.473, 2: 0.101, 3: 0.102}
REVENUE_SHARE = {0: 0.441, 1: 0.240, 2: 0.284, 3: 0.035}

FIGURES = [
    choose_k.ELBOW_FIGURE,
    choose_k.SILHOUETTE_FIGURE,
    scaling_matters.FIGURE_NAME,
    pca_axes.FIGURE_NAME,
    segment_report.FIGURE_NAME,
    q4_choose_k.FIGURE_NAME,
    q5_pca_axes.FIGURE_NAME,
]

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual}")
    if not ok:
        print(f"     期待値: {expected}")
        failures.append(label)


def check_close(label: str, actual: float, expected: float, tol: float = TOLERANCE) -> None:
    ok = abs(float(actual) - expected) <= tol
    print(f"{'OK  ' if ok else 'NG  '} {label}: {float(actual):.4f}")
    if not ok:
        print(f"     期待値: {expected:.4f} ± {tol}")
        failures.append(label)


def check_rel(label: str, actual: float, expected: float, rel: float = RELATIVE) -> None:
    ok = abs(float(actual) - expected) <= abs(expected) * rel
    print(f"{'OK  ' if ok else 'NG  '} {label}: {float(actual):,.1f}")
    if not ok:
        print(f"     期待値: {expected:,.1f}（相対 {rel:.0%} 以内）")
        failures.append(label)


missing = [
    name for name in ("books", "customers", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()
]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 0. 本文と練習問題のスクリプトが最後まで動くこと（出力は抑制する）
# ------------------------------------------------------------------
for name in FIGURES:
    (Path(OUT_DIR) / name).unlink(missing_ok=True)

modules = [
    build_rfm,
    kmeans_basics,
    choose_k,
    scaling_matters,
    pca_axes,
    segment_report,
    q1_rfm_table,
    q2_kmeans_profile,
    q3_scaling_effect,
    q4_choose_k,
    q5_pca_axes,
    q6_segment_decision,
]
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):
        for module in modules:
            module.main()
    glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("スクリプトが最後まで動いた数", len(modules), 12)
check("図の描画で出たフォント欠落の警告の数", len(glyph_warnings), 0)

for name in FIGURES:
    path = Path(OUT_DIR) / name
    size = path.stat().st_size if path.exists() else 0
    print(f"---  {name}: {size:,} バイト")
    check(f"{name} が保存され、サイズが 0 より大きいこと", size > 0, True)

# ------------------------------------------------------------------
# 1. 母集団と 3 指標（本文 2 節）
# ------------------------------------------------------------------
info = build_rfm.summary()
check("有効注文の件数", info["valid_orders"], VALID_ORDERS)
check("売上合計（円）", info["revenue"], REVENUE)
check("顧客数 ① 全顧客", info["customers"]["all"], CUSTOMERS["all"])
check("顧客数 ② 注文が 1 件以上", info["customers"]["ordered"], CUSTOMERS["ordered"])
check("顧客数 ③ 有効注文が 1 件以上", info["customers"]["valid"], CUSTOMERS["valid"])
check("RFM 表の行数", info["n_rows"], CUSTOMERS["valid"])
check("RFM 表の列", info["columns"], FEATURES)
check("RFM 表の dtype", info["dtypes"], ["int64", "int64", "float64"])
check_close("recency の平均（日）", info["means"]["recency"], 88.0, tol=DAYS)
check_close("frequency の平均（回）", info["means"]["frequency"], FREQUENCY_MEAN, tol=0.01)
check_close("monetary の平均（円）", info["means"]["monetary"], MONETARY_MEAN, tol=0.5)
check("frequency の合計が有効注文の件数と一致すること", info["frequency_sum"], VALID_ORDERS)
check("monetary の合計が売上合計と一致すること", info["monetary_sum"], REVENUE)
check("frequency の最小値", info["min_frequency"], 1)
print(f"---  アクティブ顧客: recency <= 90 が {info['active_le']:,} 人 / recency < 90 が {info['active_lt']:,} 人")
check("アクティブ顧客（recency 90 日以内）", info["active_le"], ACTIVE)

# ------------------------------------------------------------------
# 2. k=4 のクラスタリングと profile（本文 3 節・7 節）
# ------------------------------------------------------------------
basics = kmeans_basics.analyze()
check("標準化した行列の形", basics["shape"], (CUSTOMERS["valid"], 3))
check("標準化後の平均がほぼ 0 であること", basics["mean_abs_max"] < 1e-8, True)
check("標準化後の標準偏差", [round(value, 6) for value in basics["stds"]], [1.0, 1.0, 1.0])
check("k=4 のクラスタ人数", basics["counts"], SCALED_COUNTS)
check("クラスタ人数の合計", basics["total"], CUSTOMERS["valid"])
check_rel("k=4 の inertia", basics["inertia"], SWEEP[K_MAIN][0])
check_close("k=4 のシルエット係数", basics["silhouette"], SWEEP[K_MAIN][1])
print(f"---  クラスタ中心と profile の平均の相対誤差（最大）: {basics['centers_gap_relative']:.4f}")
check("クラスタ中心が profile の平均と一致すること（相対 1% 未満）", basics["centers_match_profile"], True)

table = basics["profile"]
for cluster, (n, recency, frequency, monetary) in PROFILE.items():
    row = table.loc[cluster]
    check(f"クラスタ{cluster} の人数", int(row["n"]), n)
    check_close(f"クラスタ{cluster} の recency", row["recency"], recency, tol=COUNT_TOL)
    check_close(f"クラスタ{cluster} の frequency", row["frequency"], frequency, tol=COUNT_TOL)
    check_close(f"クラスタ{cluster} の monetary", row["monetary"], monetary, tol=YEN)
check_rel(
    "profile の frequency × 人数の合計が有効注文の件数と一致すること",
    float((table["n"] * table["frequency"]).sum()),
    float(VALID_ORDERS),
    rel=0.0001,
)
check_rel(
    "profile の monetary × 人数の合計が売上合計と一致すること",
    float((table["n"] * table["monetary"]).sum()),
    float(REVENUE),
    rel=0.0001,
)
check("profile から決めたセグメント名", basics["names"], NAMES)

# ------------------------------------------------------------------
# 3. k の決め方（本文 5 節）― エルボーは折れず、シルエットは k=3 が最良
# ------------------------------------------------------------------
sweep = choose_k.analyze()
for row in sweep["rows"]:
    expected_inertia, expected_silhouette = SWEEP[int(row["k"])]
    check_rel(f"k={int(row['k'])} の inertia", row["inertia"], expected_inertia)
    check_close(f"k={int(row['k'])} のシルエット係数", row["silhouette"], expected_silhouette)
check("シルエット係数が最大になる k", sweep["best_k_by_silhouette"], K_ALT)
check("inertia が最小になる k（常に最大の k）", sweep["min_inertia_k"], 6)
expected_drops = [SWEEP[k][0] - SWEEP[k + 1][0] for k in (2, 3, 4, 5)]
for index, (actual, expected) in enumerate(zip(sweep["drops"], expected_drops)):
    check_rel(f"k={index + 2} → {index + 3} の inertia の減り方", actual, expected, rel=0.02)
check("減り方の比が 3 つ並ぶこと", len(sweep["drop_ratios"]), 3)
# 折れ目があるなら比がぐっと小さくなる。どれも 0.4 を下回らない＝段差がない（本文 5 節）
check("減り方の比がどれも 0.4 より大きいこと", all(value > 0.4 for value in sweep["drop_ratios"]), True)
check("最後の比が 0.6 より大きいこと（なめらかに減っている）", sweep["drop_ratios"][-1] > 0.6, True)

# ------------------------------------------------------------------
# 4. スケーリングの有無で結果が変わること（本文 4 節・この章の山場）
# ------------------------------------------------------------------
scaling = scaling_matters.analyze()
check("標準化しない k=4 の人数", scaling["raw_counts"], RAW_COUNTS)
check("標準化した k=4 の人数", scaling["scaled_counts"], SCALED_COUNTS)
check("標準化しない場合のいちばん小さいクラスタ", scaling["raw_min"], min(RAW_COUNTS))
check("標準化した場合のいちばん小さいクラスタ", scaling["scaled_min"], min(SCALED_COUNTS))
check("2 通りの人数の並びが違うこと", scaling["same_counts"], False)
check("monetary の標準偏差がほかの 10 倍より大きいこと", scaling["monetary_dominates_scale"], True)
check("標準化しないと monetary だけで分かれること", scaling["raw_dominant"], "monetary")
check("標準化すると 3 指標すべてが効くこと", scaling["scaled_effective"], 3)

# ------------------------------------------------------------------
# 5. 主成分分析（本文 6 節）
# ------------------------------------------------------------------
pca = pca_axes.analyze()
for index, expected in enumerate(PCA_RATIO):
    check_close(f"第 {index + 1} 主成分の寄与率", pca["ratio"][index], expected)
for index, expected in enumerate(PCA_CUMULATIVE):
    check_close(f"第 {index + 1} 主成分までの累積寄与率", pca["cumulative"][index], expected)
for name, expected in PC1.items():
    check_close(f"第 1 主成分の係数（{name}）", pca["loadings"].loc["PC1", name], expected)
for name, expected in PC2.items():
    check_close(f"第 2 主成分の係数（{name}）", pca["loadings"].loc["PC2", name], expected)
check("符号をそろえる規則が効いていること", pca["top_is_positive"], True)
check("第 1・第 2 主成分で影響が最大の指標", pca["top_features"][:2], ["frequency", "recency"])
check_close("第 1 主成分と第 2 主成分の内積（直交）", pca["dot_pc1_pc2"], 0.0, tol=1e-6)
check("係数ベクトルの長さがすべて 1 であること", [round(value, 6) for value in pca["norms"]], [1.0, 1.0, 1.0])
check("圧縮後の座標の形", pca["coords_shape"], (CUSTOMERS["valid"], 3))

# ------------------------------------------------------------------
# 6. セグメントの報告（本文 7 節・8 節）
# ------------------------------------------------------------------
report = segment_report.analyze()
check("セグメント名", report["names"], NAMES)
for cluster, expected in CUSTOMER_SHARE.items():
    check_close(f"クラスタ{cluster} の人数の割合", report["customer_share"][cluster], expected, tol=0.002)
for cluster, expected in REVENUE_SHARE.items():
    check_close(f"クラスタ{cluster} の売上の割合", report["revenue_share"][cluster], expected, tol=0.002)
check("セグメント別売上の合計", report["total_revenue"], REVENUE)
check("k=3 と k=4 のクロス表の合計", report["cross_total"], CUSTOMERS["valid"])
check("k=3 と k=4 のクロス表の形", report["cross_shape"], (K_ALT, K_MAIN))
for seed, total in report["seed_totals"].items():
    check(f"random_state={seed} でも人数の合計が変わらないこと", total, CUSTOMERS["valid"])

# ------------------------------------------------------------------
# 7. 練習問題の解答
# ------------------------------------------------------------------
q1 = q1_rfm_table.analyze()
check("問題1 の行数", q1["n_rows"], CUSTOMERS["valid"])
check("問題1 の表が common.rfm_table() と一致すること", q1["matches_common"], True)
check("問題1 に欠損がないこと", q1["no_missing"], True)
check_close("問題1 の recency の平均", q1["means"]["recency"], 88.0, tol=DAYS)
check_close("問題1 の frequency の平均", q1["means"]["frequency"], FREQUENCY_MEAN, tol=0.01)
check_close("問題1 の monetary の平均", q1["means"]["monetary"], MONETARY_MEAN, tol=0.5)
check("問題1 の frequency の合計", q1["frequency_sum"], VALID_ORDERS)
check("問題1 の売上合計", q1["revenue"], REVENUE)
check("問題1 のアクティブ顧客", q1["active"], ACTIVE)

q2 = q2_kmeans_profile.analyze()
check("問題2 のクラスタ人数", q2["counts"], SCALED_COUNTS)
check("問題2 の合計", q2["total"], CUSTOMERS["valid"])
check_rel("問題2 の inertia", q2["inertia"], SWEEP[K_MAIN][0])
check_close("問題2 のシルエット係数", q2["silhouette"], SWEEP[K_MAIN][1])
check("問題2 のセグメント名", q2["names"], NAMES)
check("問題2 の人数が最も多いクラスタ", q2["largest"], 1)
check("問題2 の売上が最も高いクラスタ", q2["richest"], 2)
check("問題2 の最終購入がいちばん前のクラスタ", q2["oldest"], 3)
for cluster, (n, recency, frequency, monetary) in PROFILE.items():
    row = q2["profile"].loc[cluster]
    check(f"問題2 のクラスタ{cluster} の人数", int(row["n"]), n)
    check_close(f"問題2 のクラスタ{cluster} の recency", row["recency"], recency, tol=COUNT_TOL)
    check_close(f"問題2 のクラスタ{cluster} の frequency", row["frequency"], frequency, tol=COUNT_TOL)
    check_close(f"問題2 のクラスタ{cluster} の monetary", row["monetary"], monetary, tol=YEN)

q3 = q3_scaling_effect.analyze()
check("問題3 の標準化なしの人数", q3["raw_counts"], RAW_COUNTS)
check("問題3 の標準化ありの人数", q3["scaled_counts"], SCALED_COUNTS)
check("問題3 の標準化なしの多い順", q3["raw_sorted"], sorted(RAW_COUNTS, reverse=True))
check("問題3 の標準化ありの多い順", q3["scaled_sorted"], sorted(SCALED_COUNTS, reverse=True))
check("問題3 の人数の並びが違うこと", q3["same_counts"], False)
check("問題3 の合計", q3["totals"], (CUSTOMERS["valid"], CUSTOMERS["valid"]))
check("問題3 の標準化なしで支配する指標", q3["raw_dominant"], "monetary")
check("問題3 の標準化ありで効く指標の数", q3["scaled_effective"], 3)

q4 = q4_choose_k.analyze()
for row in q4["rows"]:
    expected_inertia, expected_silhouette = SWEEP[int(row["k"])]
    check_rel(f"問題4 の k={int(row['k'])} の inertia", row["inertia"], expected_inertia)
    check_close(f"問題4 の k={int(row['k'])} のシルエット係数", row["silhouette"], expected_silhouette)
check("問題4 のシルエット係数が最大の k", q4["best_k"], K_ALT)
check("問題4 のシルエット係数が最小の k", q4["worst_k"], 6)
check("問題4 の inertia が単調に減ること", q4["inertia_is_monotonic"], True)
check("問題4 のシルエット係数は単調でないこと", q4["silhouette_is_monotonic"], False)

q5 = q5_pca_axes.analyze()
for index, expected in enumerate(PCA_RATIO):
    check_close(f"問題5 の PC{index + 1} の寄与率", q5["ratio"][index], expected)
for index, expected in enumerate(PCA_CUMULATIVE):
    check_close(f"問題5 の PC{index + 1} までの累積寄与率", q5["cumulative"][index], expected)
check_close("問題5 の寄与率の合計", q5["ratio_sum"], 1.0, tol=1e-6)
for name, expected in PC1.items():
    check_close(f"問題5 の PC1 の係数（{name}）", q5["loadings"].loc["PC1", name], expected)
for name, expected in PC2.items():
    check_close(f"問題5 の PC2 の係数（{name}）", q5["loadings"].loc["PC2", name], expected)
check("問題5 の PC1 で最も強い指標", q5["pc1_top"], "frequency")
check("問題5 の PC2 で最も強い指標", q5["pc2_top"], "recency")
check("問題5 の PC1 の符号の向き", q5["pc1_signs"], {"recency": "負", "frequency": "正", "monetary": "正"})
check_close("問題5 の PC1・PC2 の内積", q5["dot"], 0.0, tol=1e-6)
check("問題5 の座標の形", q5["coords_shape"], (CUSTOMERS["valid"], 3))

q6 = q6_segment_decision.analyze()
check("問題6 のセグメント名", q6["names"], NAMES)
check("問題6 のクロス表の合計", q6["cross_total"], CUSTOMERS["valid"])
check("問題6 のクロス表の形", q6["cross_shape"], (K_ALT, K_MAIN))
check("問題6 の売上合計", q6["revenue_total"], REVENUE)
check("問題6 の売上が最大のセグメント", q6["top_revenue_segment"], NAMES[0])
check("問題6 の売上が最小のセグメント", q6["smallest_revenue_segment"], NAMES[3])
check_close("問題6 の k=3 のシルエット係数", q6["silhouette"][K_ALT], SWEEP[K_ALT][1])
check_close("問題6 の k=4 のシルエット係数", q6["silhouette"][K_MAIN], SWEEP[K_MAIN][1])
for cluster, expected in CUSTOMER_SHARE.items():
    check_close(
        f"問題6 のクラスタ{cluster} の人数の割合",
        float(q6["report"].loc[cluster, "customer_share"]),
        expected,
        tol=0.002,
    )
for cluster, expected in REVENUE_SHARE.items():
    check_close(
        f"問題6 のクラスタ{cluster} の売上の割合",
        float(q6["report"].loc[cluster, "revenue_share"]),
        expected,
        tol=0.002,
    )

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 27 のすべての検証に成功しました。")
