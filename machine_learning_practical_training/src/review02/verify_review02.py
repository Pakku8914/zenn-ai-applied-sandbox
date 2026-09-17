"""横断復習② の検証スクリプト。

「横断復習②：モデルを作る ― セッション15〜19の総点検」の練習問題と解答に載せた
数値・判定・図が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/review02/verify_review02.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import numpy as np
from lightgbm import LGBMClassifier
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import Lasso, LogisticRegression, Ridge
from sklearn.tree import DecisionTreeClassifier

import q7_baseline_gap
import q8_overfit_diagnosis
import q9_coefficient_report
import q10_model_ranking
from common import (
    CLF_FEATURES,
    CLF_TARGET,
    DATA_DIR,
    MAX_ITER,
    N_ESTIMATORS,
    OUT_DIR,
    RANDOM_STATE,
    REG_CORE_FEATURES,
    REG_FEATURES,
    REG_TARGET,
    add_pages_dup,
    category_columns,
    coef_series,
    depth_table,
    fit_and_score,
    fit_linear,
    fit_ols,
    fit_penalized,
    fit_pipeline,
    fitted_feature_names,
    importance_series,
    learning_curve_of,
    load_review_table,
    logistic_coefficients,
    positive_proba,
    regression_scores,
    score_pipeline,
    split_classification,
    split_regression,
    standardize,
    threshold_table,
    vif_table,
    zero_columns,
)

TOLERANCE = 0.005  # 指標の許容誤差（本書共通）
COEF_TOLERANCE = 0.0005  # 係数の許容誤差
VIF_RELATIVE = 0.01  # VIF は桁が大きいので相対誤差で見る

# 深さ, 葉の数, 訓練 AUC, 評価 AUC, 診断
EXPECTED_DEPTHS: list[tuple[int | None, int, float, float, str]] = [
    (1, 2, 0.6492, 0.6522, "未学習（バイアスが大きい）"),
    (3, 8, 0.7487, 0.7601, "釣り合っている"),
    (5, 31, 0.7976, 0.7867, "釣り合っている"),
    (10, 378, 0.8788, 0.7503, "過学習（バリアンスが大きい）"),
    (20, 2075, 0.9963, 0.6277, "過学習（バリアンスが大きい）"),
    (None, 2376, 0.9996, 0.6125, "過学習（バリアンスが大きい）"),
]

# 閾値, 適合率, 再現率, F1, accuracy
EXPECTED_THRESHOLDS = [
    (0.3, 0.8327, 0.9941, 0.9063, 0.8321),
    (0.5, 0.8528, 0.9751, 0.9099, 0.8422),
    (0.7, 0.8906, 0.8666, 0.8785, 0.8041),
    (0.9, 0.9678, 0.5097, 0.6677, 0.5857),
]

EXPECTED_SIZES = [566, 2267, 5667, 11335]
FIGURES = ["review02_overfit_diagnosis.png", "review02_model_ranking.png"]

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


def check_coef(label: str, actual: float, expected: float, tol: float = COEF_TOLERANCE) -> None:
    """係数の検証。桁が小さいので専用の許容誤差を使う。"""
    ok = abs(actual - expected) <= tol
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:+.6f}")
    if not ok:
        print(f"     期待値: {expected:+.6f} ± {tol}")
        failures.append(label)


def check_rel(label: str, actual: float, expected: float, rel: float = VIF_RELATIVE) -> None:
    """VIF のように桁が大きい値の検証（相対誤差）。"""
    ok = abs(actual - expected) <= abs(expected) * rel
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:,.3f}")
    if not ok:
        print(f"     期待値: {expected:,.3f} ± {rel:.0%}")
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
# 1. 母集団と分割（C部のすべての章と同じ表・同じ並び・同じ分割）
# ------------------------------------------------------------------
df = load_review_table()
X_train, X_test, y_train, y_test = split_classification(df)
check("学習に使うレビュー件数", len(df), 14169)
check("訓練データの件数", len(X_train), 10626)
check("評価データの件数", len(X_test), 3543)
check("分割の合計", len(X_train) + len(X_test), 14169)
check("特徴量の列数（One-Hot にする前）", X_train.shape[1], 5)
check_close("正例率（訓練）", float(y_train.mean()), 0.8167, tol=0.0001)
check_close("正例率（評価）", float(y_test.mean()), 0.8168, tol=0.0001)
check("訓練と評価に同じ行が入っていないこと", len(set(X_train.index) & set(X_test.index)), 0)
check("unit_price が書籍マスタの price と同じ値であること", bool((df["unit_price"] == df["price"]).all()), True)
check_close("corr(pages, unit_price)", float(df["pages"].corr(df["unit_price"])), 0.9709)

# ------------------------------------------------------------------
# 2. ベースラインとの比較（実装 7）
# ------------------------------------------------------------------
base = fit_and_score(
    DummyClassifier(strategy="most_frequent", random_state=RANDOM_STATE), X_train, y_train, X_test, y_test
)
logistic = fit_and_score(
    LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE), X_train, y_train, X_test, y_test
)
check_close("ベースラインの accuracy", base["accuracy"], 0.8168, tol=0.0001)
check_close("ベースラインの ROC AUC", base["roc_auc"], 0.5000, tol=0.0001)
check(
    "ベースラインの accuracy が評価データの正例率と一致すること",
    bool(abs(base["accuracy"] - float(y_test.mean())) < 1e-9),
    True,
)
check_close("ロジスティック回帰の accuracy", logistic["accuracy"], 0.8422)
check_close("ロジスティック回帰の ROC AUC", logistic["roc_auc"], 0.8265)
check_close("ロジスティック回帰の対数損失", logistic["log_loss"], 0.3592)
gain = logistic["accuracy"] - base["accuracy"]
check_close("accuracy の改善幅", gain, 0.0254, tol=0.0005)
check("accuracy の改善の表示（ポイント）", f"{gain * 100:.1f}", "2.5")
check("accuracy の改善が 3 ポイント未満であること", bool(gain < 0.03), True)
check("ベースラインの対数損失のほうが大きいこと", bool(base["log_loss"] > logistic["log_loss"]), True)

# ------------------------------------------------------------------
# 3. 係数とオッズ比（想起 3 の照合用）
# ------------------------------------------------------------------
logistic_pipeline = fit_pipeline(
    LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE), X_train, y_train
)
coefs = logistic_coefficients(logistic_pipeline)
names = fitted_feature_names(logistic_pipeline)
categories = category_columns(names)
check("One-Hot にした後の列数", len(names), 9)
check("カテゴリ列の並び", categories, ["category_ビジネス", "category_児童書", "category_実用書", "category_小説", "category_技術書"])
check_close("unit_price の係数", float(coefs["unit_price"]), -2.4773)
check_close("pages の係数", float(coefs["pages"]), 1.3008)
check_close("published_year の係数", float(coefs["published_year"]), -0.0084)
check_close("body_length の係数", float(coefs["body_length"]), -0.7365)
check_close("category_児童書 の係数", float(coefs["category_児童書"]), 1.6021)
check_close("category_実用書 の係数", float(coefs["category_実用書"]), -1.6360)
check_close("切片", float(logistic_pipeline.named_steps["model"].intercept_[0]), 1.9133)
numeric_names = [name for name in names if name not in categories]
check("数値 4 列で絶対値が最大の列", str(coefs[numeric_names].abs().idxmax()), "unit_price")
check("category_児童書 の係数が正であること（高評価に寄せる）", bool(coefs["category_児童書"] > 0), True)
check("category_実用書 の係数が負であること（高評価から遠ざける）", bool(coefs["category_実用書"] < 0), True)
check_close("unit_price のオッズ比", float(np.exp(coefs["unit_price"])), 0.0840, tol=0.01)
check_close("pages のオッズ比", float(np.exp(coefs["pages"])), 3.6723, tol=0.01)
check_close("category_児童書 のオッズ比", float(np.exp(coefs["category_児童書"])), 4.9635, tol=0.01)
check_close("category_実用書 のオッズ比", float(np.exp(coefs["category_実用書"])), 0.1948, tol=0.01)

# ------------------------------------------------------------------
# 4. 閾値を動かしたときの指標（想起 3・実装 7）
# ------------------------------------------------------------------
proba = positive_proba(logistic_pipeline, X_test)
table = threshold_table(y_test, proba)
check("試した閾値の数", len(table), 4)
for (threshold, precision, recall, f1, accuracy), row in zip(EXPECTED_THRESHOLDS, table.itertuples(index=False)):
    check(f"閾値 {threshold} の値", float(row.threshold), threshold)
    check_close(f"閾値 {threshold} の適合率", float(row.precision), precision)
    check_close(f"閾値 {threshold} の再現率", float(row.recall), recall)
    check_close(f"閾値 {threshold} の F1", float(row.f1), f1)
    check_close(f"閾値 {threshold} の accuracy", float(row.accuracy), accuracy)
check("F1 が最大になる閾値", float(table.loc[table["f1"].idxmax(), "threshold"]), 0.5)
check(
    "閾値 0.5 の accuracy がモデルの accuracy と一致すること",
    bool(abs(float(table.loc[table["threshold"] == 0.5, "accuracy"].iloc[0]) - logistic["accuracy"]) < 1e-9),
    True,
)
check("閾値を上げると適合率が上がること", list(table["precision"]) == sorted(table["precision"]), True)
check("閾値を上げると再現率が下がること", list(table["recall"]) == sorted(table["recall"], reverse=True), True)

# ------------------------------------------------------------------
# 5. 決定木の深さと過学習（実装 8）
# ------------------------------------------------------------------
rows = depth_table(X_train, y_train, X_test, y_test)
check("試した深さの数", len(rows), len(EXPECTED_DEPTHS))
for row, (depth, leaves, train_auc, test_auc, diagnosis) in zip(rows, EXPECTED_DEPTHS):
    check(f"深さ {row['label']} の葉の数", row["leaves"], leaves)
    check_close(f"深さ {row['label']} の訓練 AUC", row["train_auc"], train_auc)
    check_close(f"深さ {row['label']} の評価 AUC", row["test_auc"], test_auc)
    check(f"深さ {row['label']} の診断", row["diagnosis"], diagnosis)
best = max(rows, key=lambda r: r["test_auc"])
deepest = max(rows, key=lambda r: r["train_auc"])
check("評価 AUC が最も高い深さ", best["label"], "5")
check("訓練 AUC が最も高い深さ", deepest["label"], "制限なし")
check("訓練の最良と評価の最良が別の深さであること", best["label"] != deepest["label"], True)
check("葉の数が深さ 1 の 1,000 倍以上になること", bool(rows[-1]["leaves"] >= rows[0]["leaves"] * 1000), True)
check("未学習と診断された深さの数", [r["diagnosis"] for r in rows].count("未学習（バイアスが大きい）"), 1)
check("過学習と診断された深さの数", [r["diagnosis"] for r in rows].count("過学習（バリアンスが大きい）"), 3)

# ------------------------------------------------------------------
# 6. 学習曲線の 2 パターン（実装 8）
# ------------------------------------------------------------------
linear_curve = learning_curve_of(
    LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE), df[CLF_FEATURES], df[CLF_TARGET]
)
tree_curve = learning_curve_of(
    DecisionTreeClassifier(random_state=RANDOM_STATE), df[CLF_FEATURES], df[CLF_TARGET]
)
check("学習曲線の件数", linear_curve["sizes"], EXPECTED_SIZES)
check("決定木の学習曲線の件数", tree_curve["sizes"], EXPECTED_SIZES)
check_close("ロジスティック回帰の訓練 AUC（566 件）", linear_curve["train"][0], 0.8522)
check_close("ロジスティック回帰の訓練 AUC（11,335 件）", linear_curve["train"][-1], 0.8246)
check_close("ロジスティック回帰の検証 AUC（566 件）", linear_curve["valid"][0], 0.8181)
check_close("ロジスティック回帰の検証 AUC（11,335 件）", linear_curve["valid"][-1], 0.8240)
check_close("決定木の訓練 AUC（566 件）", tree_curve["train"][0], 1.0000)
check_close("決定木の訓練 AUC（11,335 件）", tree_curve["train"][-1], 0.9995)
check_close("決定木の検証 AUC（566 件）", tree_curve["valid"][0], 0.5949)
check_close("決定木の検証 AUC（11,335 件）", tree_curve["valid"][-1], 0.6091)
check(
    "ロジスティック回帰は最大件数で 2 本が接近すること（差 < 0.01）",
    bool(linear_curve["train"][-1] - linear_curve["valid"][-1] < 0.01),
    True,
)
check(
    "決定木は最大件数でも 2 本が開いたままであること（差 > 0.30）",
    bool(tree_curve["train"][-1] - tree_curve["valid"][-1] > 0.30),
    True,
)
check(
    "件数を 20 倍にしたロジスティック回帰の検証 AUC の伸びが 0.01 未満であること",
    bool(linear_curve["valid"][-1] - linear_curve["valid"][0] < 0.01),
    True,
)
check(
    "決定木の検証 AUC が一度もロジスティック回帰を上回らないこと",
    bool(max(tree_curve["valid"]) < min(linear_curve["valid"])),
    True,
)

# ------------------------------------------------------------------
# 7. 木モデルの重要度（実装 9）
# ------------------------------------------------------------------
forest = fit_pipeline(
    RandomForestClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=1), X_train, y_train
)
forest_scores = score_pipeline(forest, X_test, y_test)
forest_importance = importance_series(forest)
check_close("ランダムフォレストの accuracy", forest_scores["accuracy"], 0.7959)
check_close("ランダムフォレストの ROC AUC", forest_scores["roc_auc"], 0.7705)
check_close("重要度 body_length", float(forest_importance["body_length"]), 0.5479)
check_close("重要度 unit_price", float(forest_importance["unit_price"]), 0.1793)
check_close("重要度 pages", float(forest_importance["pages"]), 0.1431)
check_close("重要度 published_year", float(forest_importance["published_year"]), 0.0707)
check_close("重要度の合計が 1 になること", float(forest_importance.sum()), 1.0, tol=1e-6)
check("重要度の合計（数値 4 列）の表示", f"{forest_importance[numeric_names].sum():.3f}", "0.941")
check("重要度の合計（カテゴリ 5 列）の表示", f"{forest_importance[categories].sum():.3f}", "0.059")
check("重要度が最大の列", str(forest_importance.idxmax()), "body_length")

shallow = fit_pipeline(DecisionTreeClassifier(max_depth=3, random_state=RANDOM_STATE), X_train, y_train)
shallow_importance = importance_series(shallow)
check_close("深さ 3 の重要度 body_length", float(shallow_importance["body_length"]), 0.4176)
check_close("深さ 3 の重要度 unit_price", float(shallow_importance["unit_price"]), 0.4113)
check_close("深さ 3 の重要度 category_実用書", float(shallow_importance["category_実用書"]), 0.1710)
check("深さ 3 の重要度 pages がちょうど 0 であること", float(shallow_importance["pages"]), 0.0)
check("深さ 3 の重要度 published_year がちょうど 0 であること", float(shallow_importance["published_year"]), 0.0)
check(
    "深さ 3 で 1 度も使われなかった列",
    [str(name) for name in shallow_importance[shallow_importance == 0].index],
    ["pages", "published_year", "category_ビジネス", "category_児童書", "category_小説", "category_技術書"],
)
check(
    "ランダムフォレストと深さ 3 の木で最重要の列が同じであること",
    str(forest_importance.idxmax()) == str(shallow_importance.idxmax()),
    True,
)
check(
    "ロジスティック回帰の最重要（unit_price）と木の最重要（body_length）が食い違うこと",
    str(coefs[numeric_names].abs().idxmax()) != str(forest_importance[numeric_names].idxmax()),
    True,
)

# ------------------------------------------------------------------
# 8. 4 種類のモデルの順位（実装 10）
# ------------------------------------------------------------------
lgbm_default = fit_and_score(
    LGBMClassifier(n_estimators=N_ESTIMATORS, learning_rate=0.1, random_state=RANDOM_STATE, verbose=-1),
    X_train,
    y_train,
    X_test,
    y_test,
)
lgbm_slow = fit_and_score(
    LGBMClassifier(n_estimators=N_ESTIMATORS, learning_rate=0.05, random_state=RANDOM_STATE, verbose=-1),
    X_train,
    y_train,
    X_test,
    y_test,
)
lgbm_short = fit_and_score(
    LGBMClassifier(n_estimators=50, learning_rate=0.05, random_state=RANDOM_STATE, verbose=-1),
    X_train,
    y_train,
    X_test,
    y_test,
)
check_close("LightGBM（既定 200 本・lr 0.1）の accuracy", lgbm_default["accuracy"], 0.8323)
check_close("LightGBM（既定 200 本・lr 0.1）の ROC AUC", lgbm_default["roc_auc"], 0.7966)
check_close("LightGBM（200 本・lr 0.05）の accuracy", lgbm_slow["accuracy"], 0.8377)
check_close("LightGBM（200 本・lr 0.05）の ROC AUC", lgbm_slow["roc_auc"], 0.8065)
check_close("LightGBM（50 本・lr 0.05）の accuracy", lgbm_short["accuracy"], 0.8400)
check_close("LightGBM（50 本・lr 0.05）の ROC AUC", lgbm_short["roc_auc"], 0.8110)

ranking = sorted(
    [
        ("ベースライン", base),
        ("ロジスティック回帰", logistic),
        ("ランダムフォレスト", forest_scores),
        ("LightGBM（既定）", lgbm_default),
        ("LightGBM（200 本・lr 0.05）", lgbm_slow),
        ("LightGBM（50 本・lr 0.05）", lgbm_short),
    ],
    key=lambda pair: pair[1]["roc_auc"],
    reverse=True,
)
check(
    "ROC AUC の順位",
    [name for name, _ in ranking],
    [
        "ロジスティック回帰",
        "LightGBM（50 本・lr 0.05）",
        "LightGBM（200 本・lr 0.05）",
        "LightGBM（既定）",
        "ランダムフォレスト",
        "ベースライン",
    ],
)
check("ROC AUC の 1 位がロジスティック回帰であること", ranking[0][0], "ロジスティック回帰")
check(
    "accuracy の 1 位もロジスティック回帰であること",
    bool(logistic["accuracy"] > max(s["accuracy"] for s in (forest_scores, lgbm_default, lgbm_slow, lgbm_short))),
    True,
)
check(
    "木モデルの最良がロジスティック回帰に届かないこと",
    bool(max(s["roc_auc"] for s in (forest_scores, lgbm_default, lgbm_slow, lgbm_short)) < logistic["roc_auc"]),
    True,
)
check("LightGBM は既定値が最良ではないこと", bool(lgbm_short["roc_auc"] > lgbm_default["roc_auc"]), True)
check("木の本数を 200 から 50 に減らしても良くなること", bool(lgbm_short["roc_auc"] > lgbm_slow["roc_auc"]), True)

# ------------------------------------------------------------------
# 9. 星の回帰（実装 9 の根拠）
# ------------------------------------------------------------------
X_reg_train, X_reg_test, y_reg_train, y_reg_test = split_regression(df)
check("回帰の訓練データの件数", len(X_reg_train), 10626)
check("回帰の評価データの件数", len(X_reg_test), 3543)
raw_model = fit_linear(X_reg_train, y_reg_train)
raw_coefs = coef_series(raw_model, X_reg_train.columns)
check_coef("price の係数（生スケール）", float(raw_coefs["price"]), -0.000455, tol=2e-5)
check_coef("pages の係数（生スケール）", float(raw_coefs["pages"]), 0.001524, tol=2e-5)
check_coef("published_year の係数（生スケール）", float(raw_coefs["published_year"]), -0.001784, tol=2e-5)
check_coef("body_length の係数（生スケール）", float(raw_coefs["body_length"]), -0.002498, tol=2e-5)
check_close("回帰の切片", float(raw_model.intercept_), 8.1589)
check("生スケールで絶対値が最大の列", str(raw_coefs.abs().idxmax()), "body_length")

scores = regression_scores(raw_model, X_reg_test, y_reg_test)
check_close("回帰の R2", scores["r2"], 0.2060)
check_close("回帰の MAE", scores["mae"], 0.3954)
check_close("回帰の RMSE", scores["rmse"], 0.5267)

X_reg_train_s, X_reg_test_s, _ = standardize(X_reg_train, X_reg_test)
std_model = fit_linear(X_reg_train_s, y_reg_train)
std_coefs = coef_series(std_model, X_reg_train_s.columns)
check_close("price の係数（標準化後）", float(std_coefs["price"]), -0.4227)
check_close("pages の係数（標準化後）", float(std_coefs["pages"]), 0.2429)
check_close("published_year の係数（標準化後）", float(std_coefs["published_year"]), -0.0060)
check_close("body_length の係数（標準化後）", float(std_coefs["body_length"]), -0.1687)
check("標準化後に絶対値が最大の列", str(std_coefs.abs().idxmax()), "price")
check_close(
    "price は body_length の何倍か（標準化後）",
    abs(float(std_coefs["price"])) / abs(float(std_coefs["body_length"])),
    2.5,
    tol=0.05,
)
check(
    "標準化しても R2 が変わらないこと",
    bool(abs(regression_scores(std_model, X_reg_test_s, y_reg_test)["r2"] - scores["r2"]) < 1e-9),
    True,
)

ols = fit_ols(X_reg_train, y_reg_train)
check("statsmodels の観測数", int(ols.nobs), 10626)
check_close("statsmodels の R2（訓練データ）", float(ols.rsquared), 0.1921)
check_close("statsmodels の調整済み R2", float(ols.rsquared_adj), 0.1918)
check_range("price の p 値", float(ols.pvalues["price"]), 1e-84, 1e-82)
check_range("pages の p 値", float(ols.pvalues["pages"]), 1e-29, 1e-28)
check_range("body_length の p 値", float(ols.pvalues["body_length"]), 1e-224, 1e-222)
check_close("published_year の p 値", float(ols.pvalues["published_year"]), 0.2425)
check("p < 0.05 だった列", [name for name in REG_FEATURES if ols.pvalues[name] < 0.05], ["price", "pages", "body_length"])
conf = ols.conf_int()  # 列名に頼らず位置（1 列目が下限・2 列目が上限）で取り出す
check_coef("price の 95% 信頼区間の下限", float(conf.loc["price"].iloc[0]), -0.000501, tol=2e-5)
check_coef("price の 95% 信頼区間の上限", float(conf.loc["price"].iloc[1]), -0.000409, tol=2e-5)
check(
    "published_year の信頼区間が 0 をまたぐこと",
    bool(conf.loc["published_year"].iloc[0] < 0 < conf.loc["published_year"].iloc[1]),
    True,
)

# ------------------------------------------------------------------
# 10. 多重共線性（実装 9 の根拠・14,169 件すべてで見る）
# ------------------------------------------------------------------
vif = vif_table(df[REG_FEATURES])
check_rel("price の VIF", float(vif["price"]), 17.432)
check_rel("pages の VIF", float(vif["pages"]), 17.432)
check("published_year の VIF が 1 前後であること", bool(float(vif["published_year"]) < 1.1), True)
check("body_length の VIF が 1 前後であること", bool(float(vif["body_length"]) < 1.1), True)
check("VIF が 10 を超えた列", [str(name) for name, value in vif.items() if value > 10], ["price", "pages"])
check_close("corr(pages, price)", float(df["pages"].corr(df["price"])), 0.9709)

dup = add_pages_dup(df)
dup_features = REG_CORE_FEATURES + ["pages_dup"]
vif_dup = vif_table(dup[dup_features])
check("pages_dup を足したあとの行数", len(dup), 14169)
check_rel("pages の VIF（写しあり）", float(vif_dup["pages"]), 911199.0)
check_rel("pages_dup の VIF（写しあり）", float(vif_dup["pages_dup"]), 911107.0)
check(
    "VIF が 10 を超えた列（写しあり）",
    [str(name) for name, value in vif_dup.items() if value > 10],
    ["price", "pages", "pages_dup"],
)
plain = fit_ols(df[REG_CORE_FEATURES], df[REG_TARGET])
shaken = fit_ols(dup[dup_features], df[REG_TARGET])
check_coef("写しなしの pages の係数", float(plain.params["pages"]), 0.001524, tol=2e-5)
check_coef("写しありの pages の係数", float(shaken.params["pages"]), -0.00915)
check_close("写しありの pages の p 値", float(shaken.pvalues["pages"]), 0.7311)
check("写しありで pages が有意でないこと", bool(shaken.pvalues["pages"] >= 0.05), True)
check("pages の係数の符号が反転すること", bool(plain.params["pages"] > 0 > shaken.params["pages"]), True)
check(
    "写しを足しても当てはまり（R2）がほとんど変わらないこと",
    bool(abs(plain.rsquared - shaken.rsquared) < 0.001),
    True,
)

# ------------------------------------------------------------------
# 11. 正則化（実装 9 の対処）
# ------------------------------------------------------------------
ridge_expected = {0.1: (-0.4226, 0.2060), 100.0: (-0.3405, 0.2047)}
for alpha, (expected_coef, expected_r2) in ridge_expected.items():
    penalized, r2_ridge = fit_penalized(
        Ridge(alpha=alpha), X_reg_train_s, y_reg_train, X_reg_test_s, y_reg_test
    )
    check_close(f"Ridge α={alpha} の price の係数", float(penalized["price"]), expected_coef)
    check_close(f"Ridge α={alpha} の R2", r2_ridge, expected_r2)
    check(f"Ridge α={alpha} でゼロになった列が無いこと", zero_columns(penalized), [])

lasso_expected = {
    0.001: ([], 0.2057),
    0.01: (["pages", "published_year"], 0.1945),
    1.0: (["price", "pages", "published_year", "body_length"], 0.0),
}
for alpha, (expected_zeros, expected_r2) in lasso_expected.items():
    penalized, r2_lasso = fit_penalized(
        Lasso(alpha=alpha), X_reg_train_s, y_reg_train, X_reg_test_s, y_reg_test
    )
    check(f"Lasso α={alpha} でゼロになった列", zero_columns(penalized), expected_zeros)
    check_close(f"Lasso α={alpha} の R2", r2_lasso, expected_r2)

# ------------------------------------------------------------------
# 12. 解答スクリプトが最後まで動き、図が保存されること
# ------------------------------------------------------------------
check("問題9 で直す報告文の数", len(q9_coefficient_report.WRONG_CLAIMS), 3)
check("問題10 で挙げる理由の数", len(q10_model_ranking.REASONS), 6)
check("問題10 で比べるモデルの数", len(q10_model_ranking.build_models()), 6)

for name in FIGURES:
    (Path(OUT_DIR) / name).unlink(missing_ok=True)  # 「残っていただけ」を合格にしない

modules = [q7_baseline_gap, q8_overfit_diagnosis, q9_coefficient_report, q10_model_ranking]
executed: list[str] = []
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):  # 各スクリプトの出力は抑制する
        for module in modules:
            module.main()  # 例外が出ればここで検証が止まる
            executed.append(module.__name__)
glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("例外なく動いたスクリプトの数", len(executed), len(modules))
check("日本語フォントの欠落警告の数", len(glyph_warnings), 0)
# 収束の警告は件数だけ表示する（出た場合は max_iter を増やす合図。隠さず残す）
convergence = [w for w in caught if type(w.message).__name__ == "ConvergenceWarning"]
print(f"---  収束に関する警告の数: {len(convergence)}")

for name in FIGURES:
    path = Path(OUT_DIR) / name
    size = path.stat().st_size if path.exists() else 0
    print(f"---  {name}: {size:,} バイト")
    check(f"{name} が保存され、サイズが 0 より大きいこと", size > 0, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("横断復習② のすべての検証に成功しました。")
