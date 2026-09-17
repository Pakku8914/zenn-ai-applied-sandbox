"""セッション 19 の検証スクリプト。

「セッション19：勾配ブースティング（LightGBM）」の本文・練習問題・解答に載せた
数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session19/verify_19.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

import boosting_vs_bagging
import early_stopping
import fit_lightgbm
import gain_importance as gain_importance_script
import native_categorical
import num_leaves_effect
import param_grid
import q1_tree_count_curve
import q2_param_table
import q3_gain_table
import q4_early_stopping
import q5_native_categorical
import q6_model_comparison
from common import (
    DATA_DIR,
    MANY_ESTIMATORS,
    NUMERIC,
    OUT_DIR,
    fit_and_score,
    gain_importance,
    load_review_table,
    make_lgbm,
    logloss_curve,
    prepare,
    proba_at,
    scores_from_proba,
    split_xy,
    tree_leaf_counts,
)

TOLERANCE = 0.005  # 指標の許容誤差（本書共通）

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
# 既定のパラメータ（200 本・lr 0.1・num_leaves 31）
EXPECTED_DEFAULT = {"accuracy": 0.8323, "roc_auc": 0.7966}
# (n_estimators, learning_rate) -> (accuracy, ROC AUC)
EXPECTED_GRID = {
    (50, 0.05): (0.8400, 0.8110),
    (50, 0.1): (0.8383, 0.8110),
    (200, 0.05): (0.8377, 0.8065),
    (200, 0.1): (0.8323, 0.7966),
}
EXPECTED_BEST_ITERATION = 82
EXPECTED_EARLY_ROC_AUC = 0.8124
# gain ベースの重要度（importance_type="gain"・200 本・既定パラメータ）
# 小さな gain は丸め方で ±1 変わるので、int()（切り捨て）で厳密一致を見る
EXPECTED_GAIN = {
    "unit_price": 9185,
    "body_length": 8792,
    "pages": 2678,
    "published_year": 1206,
    "category_実用書": 1092,
    "category_児童書": 427,
    "category_ビジネス": 318,
    "category_小説": 164,
    "category_技術書": 44,
}
EXPECTED_GAIN_ORDER = list(EXPECTED_GAIN.keys())
# 4 つの予測の比較（accuracy・ROC AUC）。早期終了の行は AUC だけを本文に載せている
EXPECTED_COMPARISON = {
    "ベースライン（全部 高評価）": (0.8168, 0.5000),
    "ロジスティック回帰": (0.8422, 0.8265),
    "ランダムフォレスト": (0.7959, 0.7705),
    "LightGBM（既定 200 本）": (0.8323, 0.7966),
}
EXPECTED_NATIVE_ROC_AUC = 0.7951  # category 型のまま渡した場合（One-Hot の 0.7966 とほぼ同じ）
EXPECTED_CATEGORIES = ["ビジネス", "児童書", "実用書", "小説", "技術書"]
EXPECTED_MAX_LEAVES_WITH_DEPTH_3 = 8  # 深さ 3 なら葉は 2 の 3 乗まで
FIGURES = [
    "s19_boosting_vs_bagging.png",
    "s19_param_grid.png",
    "s19_learning_curve.png",
    "s19_gain_importance.png",
]

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


def check_truncated(label: str, actual: float, expected: int) -> None:
    """gain の検証。表示と同じ int()（切り捨て）にそろえて厳密に一致を見る。"""
    check(label, int(actual), expected)


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

# ------------------------------------------------------------------
# 2. 既定パラメータの LightGBM（本文 2 節）
# ------------------------------------------------------------------
default_model, default_scores = fit_and_score(make_lgbm(), train, y_train, test, y_test)
check_close("既定 LightGBM の accuracy", default_scores["accuracy"], EXPECTED_DEFAULT["accuracy"])
check_close("既定 LightGBM の ROC AUC", default_scores["roc_auc"], EXPECTED_DEFAULT["roc_auc"])
check("既定 LightGBM の木の本数", int(default_model.booster_.num_trees()), 200)
check(
    "1 本の木の葉が num_leaves（31）を超えないこと",
    max(tree_leaf_counts(default_model)) <= 31,
    True,
)

# ブースティングは足し算なので、200 本を先頭 50 本で打ち切ると 50 本で学習した結果と一致する
truncated = float(roc_auc_score(y_test, proba_at(default_model, test, 50)))
_, fifty = fit_and_score(make_lgbm(n_estimators=50), train, y_train, test, y_test)
check_close("先頭 50 本で打ち切った ROC AUC", truncated, EXPECTED_GRID[(50, 0.1)][1])
check(
    "打ち切った予測と 50 本で学習した予測の ROC AUC が一致すること",
    abs(truncated - fifty["roc_auc"]) < 1e-9,
    True,
)

# ------------------------------------------------------------------
# 3. パラメータを手で 4 通り試す（本文 4 節・問題2）
# ------------------------------------------------------------------
grid = q2_param_table.build_table(df)
check("4 通りの表の行数", len(grid), 4)
for row in grid.itertuples(index=False):
    key = (int(row.n_estimators), float(row.learning_rate))
    expected_accuracy, expected_auc = EXPECTED_GRID[key]
    check_close(f"{key[0]} 本・lr {key[1]} の accuracy", float(row.accuracy), expected_accuracy)
    check_close(f"{key[0]} 本・lr {key[1]} の ROC AUC", float(row.roc_auc), expected_auc)
check("既定（200 本・lr 0.1）が 4 通りの中で最下位であること", q2_param_table.rank_of(grid, (200, 0.1)), 4)


def grid_auc(n_estimators: int, learning_rate: float) -> float:
    matched = grid[(grid["n_estimators"] == n_estimators) & (grid["learning_rate"] == learning_rate)]
    return float(matched["roc_auc"].iloc[0])


check(
    "木を 50 本から 200 本に増やすと ROC AUC が下がること（lr 0.1）",
    grid_auc(50, 0.1) > grid_auc(200, 0.1),
    True,
)
check(
    "学習率を 0.1 から 0.05 に下げると ROC AUC が上がること（200 本）",
    grid_auc(200, 0.05) > grid_auc(200, 0.1),
    True,
)
check(
    "4 通りの最良でもロジスティック回帰（0.8265）に届かないこと",
    float(grid["roc_auc"].max()) < 0.8265,
    True,
)

# ------------------------------------------------------------------
# 4. ブースティングとバギングの違い（本文 1 節・問題1）
# ------------------------------------------------------------------
boosting, bagging = q1_tree_count_curve.curves(df)
check_close("ブースティング 50 本の ROC AUC", boosting[50], EXPECTED_GRID[(50, 0.1)][1])
check_close("ブースティング 200 本の ROC AUC", boosting[200], EXPECTED_DEFAULT["roc_auc"])
check("ブースティングは 50 本より 200 本のほうが悪いこと", boosting[50] > boosting[200], True)
check_close("バギング 200 本の ROC AUC（ランダムフォレストの実測値）", bagging[200], 0.7705)
check("バギングは 5 本より 200 本のほうが良いこと", bagging[200] > bagging[5], True)

# ------------------------------------------------------------------
# 5. num_leaves と木の形（本文 3 節）
# ------------------------------------------------------------------
leaves_table = num_leaves_effect.build_table(train, y_train, test, y_test)
default_row = leaves_table[(leaves_table["num_leaves"] == 31) & (leaves_table["max_depth"] == -1)]
check_close("num_leaves 31（既定）の評価 ROC AUC", float(default_row["test_auc"].iloc[0]), EXPECTED_DEFAULT["roc_auc"])
grown = leaves_table[leaves_table["max_depth"] == -1]
check(
    "葉を増やすと訓練データの ROC AUC が上がること（7 → 127）",
    float(grown["train_auc"].iloc[-1]) > float(grown["train_auc"].iloc[0]),
    True,
)
capped_row = leaves_table[leaves_table["max_depth"] == 3]
check(
    "max_depth=3 のとき木 1 本の葉が 8 枚以下であること",
    int(capped_row["max_leaves_in_tree"].iloc[0]) <= EXPECTED_MAX_LEAVES_WITH_DEPTH_3,
    True,
)

# ------------------------------------------------------------------
# 6. 早期終了（本文 5 節・問題4）
# ------------------------------------------------------------------
stopped = early_stopping.fit_with_early_stopping(train, y_train, test, y_test)
stopped_scores = scores_from_proba(y_test, stopped.predict_proba(test)[:, 1])
check("early stopping が選んだ本数（best_iteration_）", int(stopped.best_iteration_), EXPECTED_BEST_ITERATION)
check_close("early stopping 後の ROC AUC", stopped_scores["roc_auc"], EXPECTED_EARLY_ROC_AUC)
check("上限の 1000 本に達していないこと", int(stopped.best_iteration_) < MANY_ESTIMATORS, True)
check(
    "打ち切り判定のぶんだけ余分に木が建つこと",
    EXPECTED_BEST_ITERATION <= int(stopped.booster_.num_trees()) <= EXPECTED_BEST_ITERATION + 51,
    True,
)
check("早期終了で既定 200 本より ROC AUC が上がること", stopped_scores["roc_auc"] > EXPECTED_DEFAULT["roc_auc"], True)
check("それでもロジスティック回帰（0.8265）には届かないこと", stopped_scores["roc_auc"] < 0.8265, True)

counts, train_loss, valid_loss = logloss_curve(stopped, train, y_train, test, y_test)
check("学習曲線の点の数が 1 点以上あること", len(counts) > 1, True)
check("訓練データの対数損失は最後まで下がること", train_loss[-1] < train_loss[0], True)
check("検証データの対数損失は途中で底を打つこと", min(valid_loss) < valid_loss[-1], True)

# eval_set は非推奨。警告が出ること自体を検証する（filterwarnings で隠さない）
caught_warnings = q4_early_stopping.deprecation_warnings(df)
check("eval_set を使ったときに警告が出ること", len(caught_warnings) >= 1, True)
if caught_warnings:
    warning_name, warning_message = caught_warnings[0]
    check("警告の型名", warning_name, "LGBMDeprecationWarning")
    check("警告が eval_X / eval_y を案内していること", "eval_X" in warning_message and "eval_y" in warning_message, True)

early_result = q4_early_stopping.run(df)
check("問題4 の best_iteration_", early_result["best_iteration"], EXPECTED_BEST_ITERATION)
check_close("問題4 の早期終了後の ROC AUC", early_result["stopped"]["roc_auc"], EXPECTED_EARLY_ROC_AUC)
check_close("問題4 の固定 200 本の ROC AUC", early_result["fixed"]["roc_auc"], EXPECTED_DEFAULT["roc_auc"])
check("問題4 で上限に達していないこと", early_result["hit_limit"], False)

# ------------------------------------------------------------------
# 7. gain の重要度（本文 7 節・問題3）
# ------------------------------------------------------------------
gain_model = make_lgbm(importance_type="gain").fit(train, y_train)
gain_table = gain_importance(gain_model, names)
check("重要度の表の行数", len(gain_table), 9)
check("gain の大きい順の並び", list(gain_table["feature"]), EXPECTED_GAIN_ORDER)
gains = dict(zip(gain_table["feature"], gain_table["gain"]))
for feature, expected in EXPECTED_GAIN.items():
    check_truncated(f"{feature} の gain（切り捨て）", float(gains[feature]), expected)
check(
    "importance_type='gain' を指定すると feature_importances_ が gain になること",
    bool(np.allclose(gain_model.feature_importances_, [gains[name] for name in names])),
    True,
)
q3_table = q3_gain_table.build_table(df)
check("問題3 の上位 2 列", list(q3_table["feature"].head(2)), ["unit_price", "body_length"])
check("問題3 の上位 2 列で gain の 7 割以上を占めること", q3_gain_table.top_share(q3_table) > 0.7, True)

# ------------------------------------------------------------------
# 8. カテゴリ変数をそのまま扱う（本文 6 節・問題5）
# ------------------------------------------------------------------
native = q5_native_categorical.compare(df)
check_close("One-Hot 版の ROC AUC", native["One-Hot（9 列）"]["roc_auc"], EXPECTED_DEFAULT["roc_auc"])
check_close("One-Hot 版の accuracy", native["One-Hot（9 列）"]["accuracy"], EXPECTED_DEFAULT["accuracy"])
check("One-Hot 版の列数", native["_columns"]["onehot"], 9)
check("category 型版の列数", native["_columns"]["native"], 5)
native_auc = native["category 型（5 列）"]["roc_auc"]
check_close("category 型のまま渡したときの ROC AUC", native_auc, EXPECTED_NATIVE_ROC_AUC)
check(
    "One-Hot 版と category 型版の差が許容誤差の範囲（ほぼ同じ）であること",
    abs(native_auc - EXPECTED_DEFAULT["roc_auc"]) < TOLERANCE,
    True,
)
check("このデータでは One-Hot 版のほうがわずかに高いこと", EXPECTED_DEFAULT["roc_auc"] > native_auc, True)

unknown = q5_native_categorical.unknown_level(df)
check("訓練データから決めた水準", unknown["categories"], EXPECTED_CATEGORIES)
check("知らない水準が欠損（NaN）になること", unknown["became_nan"], True)
check("知らない水準でも予測が返ること", unknown["predicted"], True)
check("文字列のまま渡すと例外になること", native_categorical.try_raw_strings(X_train, y_train), "ValueError")

# ------------------------------------------------------------------
# 9. 4 つの予測の比較（問題6）
# ------------------------------------------------------------------
comparison = q6_model_comparison.compare(df)
for label, (expected_accuracy, expected_auc) in EXPECTED_COMPARISON.items():
    tol = 1e-9 if label.startswith("ベースライン") and expected_auc == 0.5 else TOLERANCE
    check_close(f"{label} の accuracy", comparison[label]["accuracy"], expected_accuracy)
    check_close(f"{label} の ROC AUC", comparison[label]["roc_auc"], expected_auc, tol=tol)
check_close(
    "LightGBM（早期終了で調整）の ROC AUC",
    comparison["LightGBM（早期終了で調整）"]["roc_auc"],
    EXPECTED_EARLY_ROC_AUC,
)
check(
    "問題6 の early stopping が選んだ本数",
    int(comparison["LightGBM（早期終了で調整）"]["best_iteration"]),
    EXPECTED_BEST_ITERATION,
)
order = [label for label, _ in q6_model_comparison.ranking(comparison)]
check(
    "ROC AUC の順位",
    order,
    [
        "ロジスティック回帰",
        "LightGBM（早期終了で調整）",
        "LightGBM（既定 200 本）",
        "ランダムフォレスト",
    ],
)

# ------------------------------------------------------------------
# 10. 全スクリプトが実行でき、図が保存され、フォントが欠けないこと
# ------------------------------------------------------------------
modules = [
    # 本文のスクリプト
    boosting_vs_bagging,
    fit_lightgbm,
    num_leaves_effect,
    param_grid,
    early_stopping,
    native_categorical,
    gain_importance_script,
    # 練習問題の解答
    q1_tree_count_curve,
    q2_param_table,
    q3_gain_table,
    q4_early_stopping,
    q5_native_categorical,
    q6_model_comparison,
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
print("セッション 19 のすべての検証に成功しました。")
