"""セッション 20 の検証スクリプト。

「セッション20：分類の評価指標 ― 混同行列から閾値設計へ」の本文・練習問題・解答に載せた
数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session20/verify_20.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import numpy as np

import both_classes
import confusion_matrix_read
import multiclass_average
import q1_confusion_by_hand
import q2_per_class_report
import q3_roc_pr_curves
import q4_youden_threshold
import q5_cost_threshold
import q6_multiclass_average
import roc_pr_curves
import threshold_by_cost
from common import (
    COST_SETTINGS,
    DATA_DIR,
    DEFAULT_THRESHOLD,
    NEGATIVE_LABEL,
    OUT_DIR,
    POSITIVE_LABEL,
    average_scores,
    baseline_scores,
    best_cost_threshold,
    class_metrics,
    confusion_parts,
    cost_row,
    curve_scores,
    fit_high_rating,
    fit_star_model,
    load_review_table,
    multiclass_confusion,
    predict_at,
    split_star,
    split_xy,
    star_counts,
    threshold_table,
    youden_point,
)

TOLERANCE = 0.005  # 指標の許容誤差（本書共通）

# 閾値 0.5 の混同行列 [[TN, FP], [FN, TP]]
EXPECTED_CONFUSION = {"tn": 162, "fp": 487, "fn": 72, "tp": 2822}
# クラスごとの指標（適合率・再現率・F1・件数）
EXPECTED_PER_CLASS = {
    NEGATIVE_LABEL: (0.6923, 0.2496, 0.3669, 649),
    POSITIVE_LABEL: (0.8528, 0.9751, 0.9099, 2894),
}
# (閾値, 適合率, 再現率, F1, 陽性と予測した件数, accuracy) ― セッション17 の再掲
EXPECTED_THRESHOLDS = [
    (0.3, 0.8327, 0.9941, 0.9063, 3455, 0.8321),
    (0.5, 0.8528, 0.9751, 0.9099, 3309, 0.8422),
    (0.7, 0.8906, 0.8666, 0.8785, 2816, 0.8041),
    (0.8, 0.9293, 0.7263, 0.8154, 2262, 0.7313),
    (0.9, 0.9678, 0.5097, 0.6677, 1524, 0.5857),
]
# Youden 指標（TPR - FPR）が最大になる点
EXPECTED_YOUDEN = {"threshold": 0.8261, "tpr": 0.6755, "fpr": 0.1911, "youden": 0.4844}
EXPECTED_YOUDEN_CONFUSION = {"tn": 525, "fp": 124, "fn": 939, "tp": 1955}
# (見逃しの重み, 誤検出の重み) -> (総コスト最小の閾値, その総コスト, 閾値 0.5 のときの総コスト)
EXPECTED_COSTS = {
    (1, 1): (0.50, 559, 559),
    (5, 1): (0.10, 626, 847),
    (1, 5): (0.80, 1592, 2507),
}
# 星ごとの件数
EXPECTED_STAR_COUNTS = {1: 1, 2: 38, 3: 2558, 4: 9325, 5: 2247}
# 多クラスの混同行列（行 = 実測 2/3/4/5、列 = 予測 2/3/4/5）
EXPECTED_MULTICLASS_CONFUSION = [
    [1, 8, 1, 0],
    [1, 159, 484, 0],
    [0, 70, 2133, 129],
    [0, 0, 388, 169],
]
EXPECTED_MULTICLASS_SCORES = {
    "accuracy": 0.6949,
    "macro_f1": 0.4305,
    "micro_f1": 0.6949,
    "weighted_f1": 0.6542,
}
FIGURES = [
    "s20_confusion.png",
    "s20_roc_pr.png",
    "s20_cost_threshold.png",
    "s20_multiclass_confusion.png",
    "s20_q3_roc_pr.png",
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
X_train, X_test, y_train, y_test_split = split_xy(df)
check("訓練データの件数", len(X_train), 10626)
check("評価データの件数", len(X_test), 3543)
check_close("全体の正例率", float(df["is_high"].mean()), 0.8167)

y_test, proba = fit_high_rating(df)
check("評価データの並びが split_xy と一致すること", bool((y_test == y_test_split).all()), True)
check_close("評価データの正例率", float(y_test.mean()), 0.8168)

# ------------------------------------------------------------------
# 2. 閾値 0.5 の混同行列と 4 象限
# ------------------------------------------------------------------
y_pred = predict_at(proba, DEFAULT_THRESHOLD)
parts = confusion_parts(y_test, y_pred)
for key, expected in EXPECTED_CONFUSION.items():
    check(f"混同行列の {key.upper()}", parts[key], expected)
check("4 象限の合計が評価データの件数と一致すること", sum(parts.values()), len(y_test))
check("陽性と予測した件数（FP + TP）", parts["fp"] + parts["tp"], 3309)

# ------------------------------------------------------------------
# 3. クラスごとの指標と 3 通りの平均
# ------------------------------------------------------------------
for label, (precision, recall, f1, support) in EXPECTED_PER_CLASS.items():
    metrics = class_metrics(y_test, y_pred, label)
    name = "陰性（低評価）" if label == NEGATIVE_LABEL else "陽性（高評価）"
    check_close(f"{name} の適合率", metrics["precision"], precision)
    check_close(f"{name} の再現率", metrics["recall"], recall)
    check_close(f"{name} の F1", metrics["f1"], f1)
    check(f"{name} の件数", metrics["support"], support)

scores = average_scores(y_test, y_pred)
check_close("accuracy（閾値 0.5）", scores["accuracy"], 0.8422)
check_close("macro F1", scores["macro_f1"], 0.6384)
check_close("weighted F1", scores["weighted_f1"], 0.8104)
check_close("micro F1（二値では accuracy と一致する）", scores["micro_f1"], 0.8422)
check(
    "micro F1 と accuracy が一致すること",
    bool(abs(scores["micro_f1"] - scores["accuracy"]) < 1e-9),
    True,
)
check("macro F1 が weighted F1 より低いこと", bool(scores["macro_f1"] < scores["weighted_f1"]), True)

base = baseline_scores(y_test)
check_close("ベースラインの accuracy", base["accuracy"], 0.8168)
check_close("ベースラインの ROC AUC", base["roc_auc"], 0.5000, tol=1e-9)
check_close("ベースラインの PR-AUC（= 正例率）", base["pr_auc"], 0.8168)
check_close("accuracy の改善幅", scores["accuracy"] - base["accuracy"], 0.0254)

# ------------------------------------------------------------------
# 4. 閾値に依存しない指標（ROC と PR）
# ------------------------------------------------------------------
curves = curve_scores(y_test, proba)
check_close("ROC AUC", curves["roc_auc"], 0.8265)
check_close("PR-AUC", curves["pr_auc"], 0.9554)
check_close("評価データの正例率（PR のベースライン）", curves["positive_rate"], 0.8168)
check("PR-AUC が ROC AUC より高いこと（正例が多数派のため）", bool(curves["pr_auc"] > curves["roc_auc"]), True)
check_close("ROC AUC のベースラインからの伸び", curves["roc_auc"] - base["roc_auc"], 0.3265)
check_close("PR-AUC のベースラインからの伸び", curves["pr_auc"] - base["pr_auc"], 0.1386)
check(
    "伸びで比べると ROC AUC のほうが大きいこと",
    bool((curves["roc_auc"] - base["roc_auc"]) > (curves["pr_auc"] - base["pr_auc"])),
    True,
)

# ------------------------------------------------------------------
# 5. Youden 指標が最大になる閾値
# ------------------------------------------------------------------
best = youden_point(y_test, proba)
for key, expected in EXPECTED_YOUDEN.items():
    check_close(f"Youden の {key}", best[key], expected)
youden_parts = confusion_parts(y_test, predict_at(proba, best["threshold"]))
for key, expected in EXPECTED_YOUDEN_CONFUSION.items():
    check(f"Youden の閾値での {key.upper()}", youden_parts[key], expected)
check("Youden の閾値が 0.5 より大きいこと", bool(best["threshold"] > DEFAULT_THRESHOLD), True)

# ------------------------------------------------------------------
# 6. 閾値の表（セッション17 の再掲）とコストから決める閾値
# ------------------------------------------------------------------
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

for (miss_cost, alarm_cost), (threshold, total_cost, default_cost) in EXPECTED_COSTS.items():
    result = best_cost_threshold(y_test, proba, miss_cost, alarm_cost)
    check_close(f"見逃し {miss_cost} : 誤検出 {alarm_cost} の最適な閾値", result["threshold"], threshold, tol=1e-9)
    check(f"見逃し {miss_cost} : 誤検出 {alarm_cost} の総コスト", int(result["total_cost"]), total_cost)
    at_default = cost_row(y_test, proba, DEFAULT_THRESHOLD, miss_cost, alarm_cost)
    check(f"見逃し {miss_cost} : 誤検出 {alarm_cost} の 0.5 での総コスト", int(at_default["total_cost"]), default_cost)
check("コストの設定が 3 通りであること", len(COST_SETTINGS), 3)

# ------------------------------------------------------------------
# 7. 多クラス分類（星 1〜5）
# ------------------------------------------------------------------
counts = star_counts(df)
for star, expected in EXPECTED_STAR_COUNTS.items():
    check(f"星{star} の件数", int(counts.loc[star]), expected)
check("いちばん少ないクラスが 1 件であること", int(counts.min()), 1)

raised: Exception | None = None
try:
    split_star(df, stratify=True)
except ValueError as error:  # 星1 が 1 件しかないため層化できない
    raised = error
check("層化分割が ValueError になること", type(raised).__name__, "ValueError")
check("例外メッセージに least populated が含まれること", "least populated" in str(raised), True)
check("例外メッセージに cannot be less than 2 が含まれること", "cannot be less than 2" in str(raised), True)

star_X_train, star_X_test, _, _ = split_star(df)
check("多クラスの訓練データの件数", len(star_X_train), 10626)
check("多クラスの評価データの件数", len(star_X_test), 3543)

y_star, y_star_pred, star_model = fit_star_model(df)
star_scores = average_scores(y_star, y_star_pred)
for key, expected in EXPECTED_MULTICLASS_SCORES.items():
    check_close(f"多クラスの {key}", star_scores[key], expected)
check(
    "多クラスでも micro F1 は accuracy と一致すること",
    bool(abs(star_scores["micro_f1"] - star_scores["accuracy"]) < 1e-9),
    True,
)
check("モデルが知っているクラス", [int(v) for v in star_model.classes_], [1, 2, 3, 4, 5])
check("評価データに現れたクラス", [int(v) for v in np.unique(y_star)], [2, 3, 4, 5])
check("予測に現れたクラス", [int(v) for v in np.unique(y_star_pred)], [2, 3, 4, 5])

labels, matrix = multiclass_confusion(y_star, y_star_pred)
check("混同行列のラベル", labels, [2, 3, 4, 5])
check("混同行列の 16 セル", matrix.tolist(), EXPECTED_MULTICLASS_CONFUSION)
check("混同行列の合計が評価データの件数と一致すること", int(matrix.sum()), 3543)

# ------------------------------------------------------------------
# 8. 練習問題の解答コード
# ------------------------------------------------------------------
mine = q1_confusion_by_hand.count_by_hand(y_test, y_pred)
check("問題1 の手計算の 4 象限が sklearn と一致すること", mine, parts)
hand = q1_confusion_by_hand.metrics_from_parts(mine)
check_close("問題1 の適合率", hand["precision"], 0.8528)
check_close("問題1 の再現率", hand["recall"], 0.9751)
check_close("問題1 の F1", hand["f1"], 0.9099)
check_close("問題1 の accuracy", hand["accuracy"], 0.8422)
check(
    "問題1 の手計算が sklearn と一致すること",
    q1_confusion_by_hand.agrees_with_sklearn(
        hand, class_metrics(y_test, y_pred, POSITIVE_LABEL), scores
    ),
    True,
)

q2 = q2_per_class_report.report(df)
check_close("問題2 の陰性の適合率", q2["low_precision"], 0.6923)
check_close("問題2 の陰性の再現率", q2["low_recall"], 0.2496)
check_close("問題2 の陰性の F1", q2["low_f1"], 0.3669)
check("問題2 の陰性の件数", q2["low_support"], 649)
check_close("問題2 の陽性の F1", q2["high_f1"], 0.9099)
check("問題2 の陽性の件数", q2["high_support"], 2894)
check_close("問題2 の手計算の macro F1", q2["hand_macro_f1"], 0.6384)
check_close("問題2 の手計算の weighted F1", q2["hand_weighted_f1"], 0.8104)
check(
    "問題2 の手計算が sklearn の平均と一致すること",
    bool(
        abs(q2["hand_macro_f1"] - q2["macro_f1"]) < 1e-9
        and abs(q2["hand_weighted_f1"] - q2["weighted_f1"]) < 1e-9
    ),
    True,
)
check_close("問題2 の macro と weighted の差", q2["weighted_f1"] - q2["macro_f1"], 0.1720)

q3 = q3_roc_pr_curves.summary(y_test, proba)
check_close("問題3 の ROC AUC", q3["roc_auc"], 0.8265)
check_close("問題3 の PR-AUC", q3["pr_auc"], 0.9554)
check_close("問題3 の PR のベースライン", q3["baseline_pr_auc"], 0.8168)
check_close("問題3 の ROC AUC の伸び", q3["roc_gain"], 0.3265)
check_close("問題3 の PR-AUC の伸び", q3["pr_gain"], 0.1386)

q4 = q4_youden_threshold.compare(y_test, proba)
check_close("問題4 の閾値", q4["youden"]["threshold"], 0.8261)
check_close("問題4 の TPR", q4["youden"]["tpr"], 0.6755)
check_close("問題4 の FPR", q4["youden"]["fpr"], 0.1911)
check("問題4 の Youden の閾値での 4 象限", q4["at_youden"], EXPECTED_YOUDEN_CONFUSION)
check("問題4 の 0.5 での 4 象限", q4["at_default"], EXPECTED_CONFUSION)

q5_rows = q5_cost_threshold.decide(y_test, proba)
check("問題5 の行数", len(q5_rows), 3)
for row in q5_rows:
    key = (row["miss_cost"], row["alarm_cost"])
    threshold, total_cost, default_cost = EXPECTED_COSTS[key]
    check_close(f"問題5 の {key} の閾値", row["best_threshold"], threshold, tol=1e-9)
    check(f"問題5 の {key} の総コスト", int(row["best_cost"]), total_cost)
    check(f"問題5 の {key} の 0.5 での総コスト", int(row["default_cost"]), default_cost)
    check(f"問題5 の {key} の削減額", int(row["saved"]), default_cost - total_cost)

q6 = q6_multiclass_average.report(df)
check("問題6 の星の件数", q6["counts"], EXPECTED_STAR_COUNTS)
check("問題6 の例外メッセージ（部分一致）", "least populated" in q6["error_message"], True)
check_close("問題6 の accuracy", q6["accuracy"], 0.6949)
check_close("問題6 の macro F1", q6["macro_f1"], 0.4305)
check_close("問題6 の micro F1", q6["micro_f1"], 0.6949)
check_close("問題6 の weighted F1", q6["weighted_f1"], 0.6542)
check_close("問題6 の macro と weighted の差", q6["weighted_f1"] - q6["macro_f1"], 0.2237)
check("問題6 の混同行列", q6["matrix"].tolist(), EXPECTED_MULTICLASS_CONFUSION)
check("問題6 の予測に現れたクラス", q6["predicted_classes"], [2, 3, 4, 5])

# ------------------------------------------------------------------
# 9. 全スクリプトが実行でき、図が保存され、フォントが欠けないこと
# ------------------------------------------------------------------
modules = [
    # 本文のスクリプト
    confusion_matrix_read,
    both_classes,
    roc_pr_curves,
    threshold_by_cost,
    multiclass_average,
    # 練習問題の解答
    q1_confusion_by_hand,
    q2_per_class_report,
    q3_roc_pr_curves,
    q4_youden_threshold,
    q5_cost_threshold,
    q6_multiclass_average,
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
print("セッション 20 のすべての検証に成功しました。")
