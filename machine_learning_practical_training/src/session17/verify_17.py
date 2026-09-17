"""セッション 17 の検証スクリプト。

「セッション17：ロジスティック回帰 ― 確率を出す分類」の本文・練習問題・解答に載せた
数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session17/verify_17.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

import fit_logistic
import linear_vs_trees
import odds_ratio
import proba_and_threshold
import q1_sigmoid_by_hand
import q2_fit_and_report
import q3_odds_ratio_table
import q4_threshold_table
import q5_manual_proba
import q6_model_choice_report
import sigmoid_curve
from common import (
    DATA_DIR,
    NUMERIC,
    OUT_DIR,
    RANDOM_STATE,
    TEST_SIZE,
    baseline_scores,
    basic_scores,
    fit_model,
    load_review_table,
    numeric_scale,
    odds_multiplier,
    prepare,
    sigmoid,
    split_xy,
    threshold_table,
)

TOLERANCE = 0.005  # 指標・係数の許容誤差（本書共通）
DELTA_CHARS = 100

EXPECTED_NAMES = [
    "unit_price",
    "pages",
    "published_year",
    "body_length",
    "category_ビジネス",
    "category_児童書",
    "category_実用書",
    "category_小説",
    "category_技術書",
]
# 標準化後の係数（本文の表）
EXPECTED_COEF = {
    "unit_price": -2.4773,
    "pages": 1.3008,
    "published_year": -0.0084,
    "body_length": -0.7365,
    "category_ビジネス": -0.4268,
    "category_児童書": 1.6021,
    "category_実用書": -1.6360,
    "category_小説": 0.9279,
    "category_技術書": 1.2913,
}
# オッズ比（= exp(係数)）
EXPECTED_ODDS = {
    "unit_price": 0.0840,
    "pages": 3.6723,
    "published_year": 0.9916,
    "body_length": 0.4788,
    "category_ビジネス": 0.6526,
    "category_児童書": 4.9635,
    "category_実用書": 0.1948,
    "category_小説": 2.5291,
    "category_技術書": 3.6375,
}
EXPECTED_INTERCEPT = 1.9133
EXPECTED_HEAD_PROBA = [0.7573, 0.8700, 0.7188, 0.9925, 0.8685]
# (閾値, 適合率, 再現率, F1, 陽性と予測した件数, accuracy)
EXPECTED_THRESHOLDS = [
    (0.3, 0.8327, 0.9941, 0.9063, 3455, 0.8321),
    (0.5, 0.8528, 0.9751, 0.9099, 3309, 0.8422),
    (0.7, 0.8906, 0.8666, 0.8785, 2816, 0.8041),
    (0.8, 0.9293, 0.7263, 0.8154, 2262, 0.7313),
    (0.9, 0.9678, 0.5097, 0.6677, 1524, 0.5857),
]
# シグモイド関数の値（数学的に決まる値なので厳しめに見る）
EXPECTED_SIGMOID = {-3: 0.0474, -2: 0.1192, -1: 0.2689, 0: 0.5000, 1: 0.7311, 2: 0.8808, 3: 0.9526}
FIGURES = ["s17_sigmoid.png", "s17_odds_ratio.png", "s17_threshold_tradeoff.png"]

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


missing = [name for name in ("books", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. 母集団と分割（src/verify_setup.py の 5 節と同じ特徴量・同じ分割）
# ------------------------------------------------------------------
df = load_review_table()
check("星の欠損を落としたレビューの行数", len(df), 14169)
X_train, X_test, y_train, y_test = split_xy(df)
check("訓練データの件数", len(X_train), 10626)
check("評価データの件数", len(X_test), 3543)
check_close("全体の正例率", float(df["is_high"].mean()), 0.8167)

pre, train, test, names = prepare(X_train, X_test)
check("前処理後の特徴量の列数", int(train.shape[1]), 9)
check("列名の集合", sorted(names), sorted(EXPECTED_NAMES))
check("数値 4 列が先頭に並ぶこと", names[:4], NUMERIC)

model = fit_model(train, y_train)
check("反復回数が上限に達していないこと", int(model.n_iter_[0]) < 1000, True)
check("クラスの並び", [int(v) for v in model.classes_], [0, 1])

# ------------------------------------------------------------------
# 2. 本文の 3 つの指標とベースライン
# ------------------------------------------------------------------
proba_matrix = model.predict_proba(test)
proba = proba_matrix[:, 1]
scores = basic_scores(y_test, proba_matrix)
check_close("accuracy（閾値 0.5）", scores["accuracy"], 0.8422)
check_close("ROC AUC", scores["roc_auc"], 0.8265)
check_close("対数損失", scores["log_loss"], 0.3592)

base = baseline_scores(y_test)
check_close("ベースラインの accuracy", base["accuracy"], 0.8168)
check_close("ベースラインの ROC AUC", base["roc_auc"], 0.5000, tol=1e-9)
check_close("accuracy の改善幅", scores["accuracy"] - base["accuracy"], 0.0254)

# ------------------------------------------------------------------
# 3. 係数とオッズ比
# ------------------------------------------------------------------
coefs = dict(zip(names, [float(v) for v in model.coef_[0]]))
for feature, expected in EXPECTED_COEF.items():
    check_close(f"{feature} の係数", coefs[feature], expected)
check_close("切片", float(model.intercept_[0]), EXPECTED_INTERCEPT)
for feature, expected in EXPECTED_ODDS.items():
    check_close(f"{feature} のオッズ比", float(np.exp(coefs[feature])), expected)

scale = numeric_scale(pre, "body_length")
# 標準化の「1 目盛」は訓練データの母標準偏差（ddof=0）。全データの標本標準偏差とは別の値になる
check_close("body_length の 1 標準偏差（訓練データ・スケーラの値）", scale, 66.7073, tol=0.05)
check_close(
    "（参考）全データの標本標準偏差 ― これは使わない値",
    float(df["body_length"].std()),
    67.3307,
    tol=0.05,
)
check("スケーラの値と全データの標本標準偏差が別の値であること", abs(scale - float(df["body_length"].std())) > 0.05, True)
check_close(
    f"body_length が {DELTA_CHARS} 文字増えたときのオッズの倍率",
    odds_multiplier(coefs["body_length"], DELTA_CHARS, scale),
    0.3315,
)
check_close(
    "unit_price のオッズの縮み方（何分の 1 か）",
    1.0 / float(np.exp(coefs["unit_price"])),
    11.91,
    tol=0.05,
)
check_close(
    "児童書は実用書の何倍のオッズか",
    float(np.exp(coefs["category_児童書"] - coefs["category_実用書"])),
    25.49,
    tol=0.05,
)
check(
    "係数の絶対値がいちばん大きいのは unit_price であること",
    max(coefs, key=lambda name: abs(coefs[name])),
    "unit_price",
)

# ------------------------------------------------------------------
# 4. predict_proba と predict、そして閾値
# ------------------------------------------------------------------
for i, expected in enumerate(EXPECTED_HEAD_PROBA):
    check_close(f"予測確率の {i + 1} 件目", float(proba[i]), expected)
check("predict の先頭 5 件", [int(v) for v in model.predict(test)[:5]], [1, 1, 1, 1, 1])
check(
    "確率を 0.5 で切った結果が predict と一致すること",
    bool(((proba >= 0.5).astype("int64") == model.predict(test)).all()),
    True,
)

table = threshold_table(y_test, proba)
check("閾値の表の行数", len(table), 5)
for row, (threshold, precision, recall, f1, n_positive, accuracy) in zip(
    table.itertuples(index=False), EXPECTED_THRESHOLDS
):
    check_close(f"閾値 {threshold} の閾値そのもの", row.threshold, threshold, tol=1e-9)
    check_close(f"閾値 {threshold} の適合率", row.precision, precision)
    check_close(f"閾値 {threshold} の再現率", row.recall, recall)
    check_close(f"閾値 {threshold} の F1", row.f1, f1)
    check(f"閾値 {threshold} で陽性と予測した件数", row.n_positive, n_positive)
    check_close(f"閾値 {threshold} の accuracy", row.accuracy, accuracy)
check(
    "accuracy が最大になる閾値が 0.5 であること",
    float(table.loc[table["accuracy"].idxmax(), "threshold"]),
    0.5,
)
check(
    "閾値を上げると適合率が単調に上がること",
    bool((table["precision"].diff().dropna() > 0).all()),
    True,
)
check(
    "閾値を上げると再現率が単調に下がること",
    bool((table["recall"].diff().dropna() < 0).all()),
    True,
)

# ------------------------------------------------------------------
# 5. 標準化しなくても当たり方は変わらない（セッション12 の再確認）
# ------------------------------------------------------------------
X_raw = odds_ratio.unscaled_design(df)
Xr_train, Xr_test, yr_train, yr_test = train_test_split(
    X_raw, df["is_high"], test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=df["is_high"]
)
raw_auc = float(roc_auc_score(yr_test, fit_model(Xr_train, yr_train).predict_proba(Xr_test)[:, 1]))
check_close("標準化しないロジスティック回帰の ROC AUC", raw_auc, 0.8267)
check("標準化の有無で ROC AUC がほぼ変わらないこと", abs(raw_auc - scores["roc_auc"]) < TOLERANCE, True)

# ------------------------------------------------------------------
# 6. 木モデルとの比較（問題6 の解答コードで計算する）
# ------------------------------------------------------------------
comparison = q6_model_choice_report.compare(df)
check_close("ロジスティック回帰の accuracy（比較表）", comparison["ロジスティック回帰"]["accuracy"], 0.8422)
check_close("ロジスティック回帰の ROC AUC（比較表）", comparison["ロジスティック回帰"]["roc_auc"], 0.8265)
check_close("ランダムフォレストの accuracy", comparison["ランダムフォレスト"]["accuracy"], 0.7959)
check_close("ランダムフォレストの ROC AUC", comparison["ランダムフォレスト"]["roc_auc"], 0.7705)
check_close("LightGBM の accuracy", comparison["LightGBM"]["accuracy"], 0.8323)
check_close("LightGBM の ROC AUC", comparison["LightGBM"]["roc_auc"], 0.7966)
check(
    "ROC AUC が ロジスティック回帰 > LightGBM > ランダムフォレスト の順であること",
    comparison["ロジスティック回帰"]["roc_auc"]
    > comparison["LightGBM"]["roc_auc"]
    > comparison["ランダムフォレスト"]["roc_auc"],
    True,
)
check("仮説どおりの符号になっていること", q6_model_choice_report.sign_check(df), {"unit_price": True, "pages": True, "body_length": True})

# ------------------------------------------------------------------
# 7. 問題1・2・3・4・5 の解答コード
# ------------------------------------------------------------------
for z, expected in EXPECTED_SIGMOID.items():
    check_close(f"問題1 の sigmoid({z:+d})", q1_sigmoid_by_hand.sigmoid(z), expected, tol=0.0005)
check(
    "問題1 の sigmoid が common の実装と一致すること",
    all(abs(q1_sigmoid_by_hand.sigmoid(z) - float(sigmoid(z))) < 1e-12 for z in EXPECTED_SIGMOID),
    True,
)
check_close("問題1 の確率 0.8 のオッズ", q1_sigmoid_by_hand.to_odds(0.8), 4.0, tol=1e-9)
check_close("問題1 の確率 0.9 のオッズ", q1_sigmoid_by_hand.to_odds(0.9), 9.0, tol=1e-9)
check_close("問題1 の確率 0.5 の対数オッズ", q1_sigmoid_by_hand.to_logit(0.5), 0.0, tol=1e-9)
check(
    "問題1 の確率 → 対数オッズ → 確率が 1 周して戻ること",
    all(
        abs(q1_sigmoid_by_hand.sigmoid(q1_sigmoid_by_hand.to_logit(p)) - p) < 1e-12
        for p in q1_sigmoid_by_hand.PROBABILITIES
    ),
    True,
)
check_close(
    "問題1 で使う pages のオッズ比が実測値と合っていること",
    q1_sigmoid_by_hand.PAGES_ODDS_RATIO,
    float(np.exp(coefs["pages"])),
)
check_close(
    "問題1 の確率 0.50 にオッズ比を掛けた確率",
    q1_sigmoid_by_hand.apply_odds_ratio(0.5, q1_sigmoid_by_hand.PAGES_ODDS_RATIO),
    0.7860,
    tol=0.0005,
)
check_close(
    "問題1 の確率 0.90 にオッズ比を掛けた確率",
    q1_sigmoid_by_hand.apply_odds_ratio(0.9, q1_sigmoid_by_hand.PAGES_ODDS_RATIO),
    0.9706,
    tol=0.0005,
)

report = q2_fit_and_report.report(df)
check("問題2 の訓練件数", report["n_train"], 10626)
check("問題2 の評価件数", report["n_test"], 3543)
check("問題2 の特徴量の列数", report["n_features"], 9)
check_close("問題2 の accuracy", report["accuracy"], 0.8422)
check_close("問題2 の ROC AUC", report["roc_auc"], 0.8265)
check_close("問題2 の対数損失", report["log_loss"], 0.3592)
check_close("問題2 のベースライン accuracy", report["baseline_accuracy"], 0.8168)
check_close("問題2 のベースライン ROC AUC", report["baseline_roc_auc"], 0.5000, tol=1e-9)

q3_table = q3_odds_ratio_table.build_table(model, names)
check("問題3 の表の先頭は unit_price であること", q3_table.iloc[0]["feature"], "unit_price")
check("問題3 の表の行数", len(q3_table), 9)
check_close("問題3 の unit_price のオッズ比", float(q3_table.iloc[0]["odds_ratio"]), 0.0840)

q4_table = q4_threshold_table.build_table(y_test, proba)
check(
    "問題4 の表が本文の表と一致すること",
    all(
        bool(np.allclose(q4_table[column].to_numpy(dtype="float64"), table[column].to_numpy(dtype="float64")))
        for column in ["threshold", "precision", "recall", "f1", "n_positive", "accuracy"]
    ),
    True,
)
check(
    "問題4 で適合率 0.95 以上になる最小の閾値",
    q4_threshold_table.lowest_threshold_for(q4_table, "precision", 0.95),
    0.9,
)
check(
    "問題4 で再現率 0.99 以上になる最小の閾値",
    q4_threshold_table.lowest_threshold_for(q4_table, "recall", 0.99),
    0.3,
)

mine = q5_manual_proba.manual_proba(test, model)
check("問題5 の手計算が predict_proba と一致すること", bool(np.abs(mine - proba).max() < 1e-9), True)
for i, expected in enumerate(EXPECTED_HEAD_PROBA):
    check_close(f"問題5 の手計算の {i + 1} 件目", float(mine[i]), expected)

# ------------------------------------------------------------------
# 8. 全スクリプトが実行でき、図が保存され、フォントが欠けないこと
# ------------------------------------------------------------------
modules = [
    # 本文のスクリプト
    sigmoid_curve,
    fit_logistic,
    odds_ratio,
    proba_and_threshold,
    linear_vs_trees,
    # 練習問題の解答
    q1_sigmoid_by_hand,
    q2_fit_and_report,
    q3_odds_ratio_table,
    q4_threshold_table,
    q5_manual_proba,
    q6_model_choice_report,
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
print("セッション 17 のすべての検証に成功しました。")
