"""セッション 24 の検証スクリプト。

「セッション24：不均衡データ ― AUC 0.79 の落とし穴」の本文・練習問題・解答に載せた
数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session24/verify_24.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import calibration_check
import class_weight_effect
import confusion_at_default
import imbalance_overview
import q1_metric_gap
import q2_confusion_reality
import q3_threshold_table
import q4_class_weight
import q5_undersampling
import q6_report_card
import report_set
import roc_vs_pr
import threshold_sweep
import undersampling
from common import (
    DATA_DIR,
    DEFAULT_THRESHOLD,
    OUT_DIR,
    baseline_scores,
    best_f1_row,
    calibration_gap,
    calibration_points,
    cancel_probabilities,
    confusion_parts,
    describe_split,
    load_cancel_table,
    predict_at,
    report_card,
    score_summary,
    threshold_table,
)

TOLERANCE = 0.005  # 指標の許容誤差（本書共通）
BRIER_TOLERANCE = 0.001  # Brier スコアは値が小さいので細かく見る

# 母集団と分割
EXPECTED_COUNTS = {
    "n_rows": 60031,
    "n_train": 45023,
    "n_test": 15008,
    "n_train_positive": 1621,
    "n_test_positive": 541,
    "n_train_negative": 43402,
}
EXPECTED_RATES = {"rate_all": 0.0360, "rate_train": 0.0360, "rate_test": 0.0360}
# 閾値 0.5 の混同行列 [[TN, FP], [FN, TP]] = [[14438, 29], [512, 29]]
EXPECTED_CONFUSION = {"tn": 14438, "fp": 29, "fn": 512, "tp": 29}
# (閾値, 適合率, 再現率, F1, 陽性と予測した件数, 捕まえた件数, 見逃した件数)
EXPECTED_THRESHOLDS = [
    (0.1, 0.1612, 0.3993, 0.2297, 1340, 216, 325),
    (0.2, 0.2489, 0.2089, 0.2271, 454, 113, 428),
    (0.3, 0.3545, 0.1442, 0.2050, 220, 78, 463),
    (0.5, 0.5000, 0.0536, 0.0968, 58, 29, 512),
]
# 3 つの学習のしかたの指標
EXPECTED_SCORES = {
    "plain": {"roc_auc": 0.7911, "pr_auc": 0.1827, "accuracy": 0.9640, "mean_proba": 0.0352},
    "balanced": {"roc_auc": 0.7901, "pr_auc": 0.1812, "precision": 0.1204, "recall": 0.5841, "mean_proba": 0.2656},
    "under": {"roc_auc": 0.7857, "pr_auc": 0.1563, "mean_proba": 0.3570},
}
EXPECTED_BRIER = {"plain": 0.03235, "balanced": 0.12445, "under": 0.19322}
# キャリブレーション曲線（5 分位・quantile）。予測の平均と実際の割合
EXPECTED_CALIBRATION = {
    "plain": {
        "pred": [0.0022, 0.0057, 0.0127, 0.0275, 0.1279],
        "true": [0.0066, 0.0080, 0.0227, 0.0327, 0.1103],
    },
    "under": {
        "pred": [0.0531, 0.1470, 0.2844, 0.4891, 0.8112],
        "true": [0.0060, 0.0140, 0.0147, 0.0353, 0.1103],
    },
}
EXPECTED_UNDER_COUNTS = {"n_after": 3242, "n_after_positive": 1621, "n_after_negative": 1621}
FIGURES = [
    "s24_roc_pr.png",
    "s24_threshold.png",
    "s24_calibration.png",
    "s24_q6_calibration.png",
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
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:.5f}")
    if not ok:
        print(f"     期待値: {expected:.5f} ± {tol}")
        failures.append(label)


missing = [name for name in ("orders", "customers") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. 母集団と分割（src/verify_setup.py の 6 節と同じ作り方）
# ------------------------------------------------------------------
df = load_cancel_table()
counts = describe_split(df)
for key, expected in EXPECTED_COUNTS.items():
    check(f"件数: {key}", counts[key], expected)
for key, expected in EXPECTED_RATES.items():
    check_close(f"正例率: {key}", float(counts[key]), expected)
check("訓練 + 評価が母集団と一致すること", counts["n_train"] + counts["n_test"], counts["n_rows"])
check("days_since_signup が作られていること", "days_since_signup" in df.columns, True)
check("days_since_signup に欠損がないこと", int(df["days_since_signup"].isna().sum()), 0)

# ------------------------------------------------------------------
# 2. 重みなしモデル（ROC AUC と PR-AUC の乖離）
# ------------------------------------------------------------------
y_test, plain = cancel_probabilities("plain")
plain_scores = score_summary(y_test, plain)
for key, expected in EXPECTED_SCORES["plain"].items():
    check_close(f"重みなしの {key}", plain_scores[key], expected)
check_close("重みなしの Brier スコア", plain_scores["brier"], EXPECTED_BRIER["plain"], tol=BRIER_TOLERANCE)
check_close("重みなしの予測確率の平均と実際の正例率の差", abs(plain_scores["mean_proba"] - float(y_test.mean())), 0.0, tol=TOLERANCE)
check("ROC AUC が PR-AUC より大きいこと", bool(plain_scores["roc_auc"] > plain_scores["pr_auc"]), True)

base = baseline_scores(y_test)
check_close("ベースラインの accuracy", base["accuracy"], 0.9640)
check_close("ベースラインの ROC AUC", base["roc_auc"], 0.5000, tol=1e-9)
check_close("ベースラインの PR-AUC（= 正例率）", base["pr_auc"], 0.0360)
check(
    "モデルの accuracy がベースラインと一致すること（差が 0.0000 と表示される）",
    bool(abs(plain_scores["accuracy"] - base["accuracy"]) < 1e-12),
    True,
)
check_close("ROC AUC のベースラインからの伸び", plain_scores["roc_auc"] - base["roc_auc"], 0.291)
check_close("PR-AUC のベースラインからの伸び", plain_scores["pr_auc"] - base["pr_auc"], 0.147)

# ------------------------------------------------------------------
# 3. 閾値 0.5 の混同行列と、閾値を下げたときの表
# ------------------------------------------------------------------
parts = confusion_parts(y_test, predict_at(plain, DEFAULT_THRESHOLD))
for key, expected in EXPECTED_CONFUSION.items():
    check(f"混同行列の {key.upper()}", parts[key], expected)
check("4 象限の合計が評価データの件数と一致すること", sum(parts.values()), 15008)
check("陽性と予測した件数（FP + TP）", parts["fp"] + parts["tp"], 58)
check("正解した件数がベースラインと同じ 14,467 件であること", parts["tn"] + parts["tp"], 14467)

rows = threshold_table(y_test, plain)
check("閾値の表の行数", len(rows), 4)
for row, (threshold, precision, recall, f1, n_positive, tp, fn) in zip(rows, EXPECTED_THRESHOLDS):
    check_close(f"閾値 {threshold} の閾値そのもの", row["threshold"], threshold, tol=1e-9)
    check_close(f"閾値 {threshold} の適合率", row["precision"], precision)
    check_close(f"閾値 {threshold} の再現率", row["recall"], recall)
    check_close(f"閾値 {threshold} の F1", row["f1"], f1)
    check(f"閾値 {threshold} で陽性と予測した件数", row["n_positive"], n_positive)
    check(f"閾値 {threshold} で捕まえた件数", row["tp"], tp)
    check(f"閾値 {threshold} で見逃した件数", row["fn"], fn)
check("F1 がいちばん高い閾値", best_f1_row(rows)["threshold"], 0.1)
check(
    "閾値を下げると再現率が上がり適合率が下がること",
    bool(rows[0]["recall"] > rows[-1]["recall"] and rows[0]["precision"] < rows[-1]["precision"]),
    True,
)

# ------------------------------------------------------------------
# 4. class_weight="balanced"（AUC は動かず、確率が壊れる）
# ------------------------------------------------------------------
_, weighted = cancel_probabilities("balanced")
weighted_scores = score_summary(y_test, weighted)
for key, expected in EXPECTED_SCORES["balanced"].items():
    check_close(f"balanced の {key}", weighted_scores[key], expected)
check_close("balanced の Brier スコア", weighted_scores["brier"], EXPECTED_BRIER["balanced"], tol=BRIER_TOLERANCE)
check(
    "ROC AUC の差が許容誤差より小さいこと",
    bool(abs(weighted_scores["roc_auc"] - plain_scores["roc_auc"]) < TOLERANCE),
    True,
)
check(
    "PR-AUC の差が許容誤差より小さいこと",
    bool(abs(weighted_scores["pr_auc"] - plain_scores["pr_auc"]) < TOLERANCE),
    True,
)
check("再現率が上がること", bool(weighted_scores["recall"] > plain_scores["recall"]), True)
check("適合率が下がること", bool(weighted_scores["precision"] < plain_scores["precision"]), True)
check("Brier スコアが悪化すること", bool(weighted_scores["brier"] > plain_scores["brier"]), True)
weighted_parts = confusion_parts(y_test, predict_at(weighted, DEFAULT_THRESHOLD))
check("balanced が閾値 0.5 で捕まえた件数", weighted_parts["tp"], 316)
check("balanced が閾値 0.5 で見逃した件数", weighted_parts["fn"], 225)

# ------------------------------------------------------------------
# 5. アンダーサンプリング（PR-AUC が悪化し、確率が膨らむ）
# ------------------------------------------------------------------
under_counts = q5_undersampling.compare()
for key, expected in EXPECTED_UNDER_COUNTS.items():
    check(f"アンダーサンプリング後の {key}", under_counts[key], expected)
check_close("そろえた後の正例率", under_counts["rate_after"], 0.5, tol=1e-9)
check("捨てた負例の件数", under_counts["n_before_negative"] - under_counts["n_after_negative"], 41781)
check("評価データには手を加えていないこと", under_counts["n_test"], 15008)

_, under = cancel_probabilities("under")
under_scores = score_summary(y_test, under)
for key, expected in EXPECTED_SCORES["under"].items():
    check_close(f"アンダーサンプリングの {key}", under_scores[key], expected)
check_close("アンダーサンプリングの Brier スコア", under_scores["brier"], EXPECTED_BRIER["under"], tol=BRIER_TOLERANCE)
check("PR-AUC が悪化すること", bool(under_scores["pr_auc"] < plain_scores["pr_auc"]), True)
check("確率の平均が正例率から大きく離れること", bool(under_scores["mean_proba"] > 0.3), True)

# ------------------------------------------------------------------
# 6. キャリブレーション曲線（重みなしは合う・サンプリング後は外れる）
# ------------------------------------------------------------------
for kind, proba in [("plain", plain), ("under", under)]:
    prob_pred, prob_true = calibration_points(y_test, proba)
    check(f"{kind} のキャリブレーションの点の数", len(prob_pred), 5)
    for index, expected in enumerate(EXPECTED_CALIBRATION[kind]["pred"]):
        check_close(f"{kind} の予測の平均 {index + 1} 番目", prob_pred[index], expected)
    for index, expected in enumerate(EXPECTED_CALIBRATION[kind]["true"]):
        check_close(f"{kind} の実際の割合 {index + 1} 番目", prob_true[index], expected)

check_close("重みなしのずれの最大", calibration_gap(y_test, plain), 0.0176, tol=TOLERANCE)
check_close("アンダーサンプリングのずれの最大", calibration_gap(y_test, under), 0.7009, tol=TOLERANCE)
check(
    "重みなしのほうが対角線に近いこと",
    bool(calibration_gap(y_test, plain) < calibration_gap(y_test, under)),
    True,
)

# ------------------------------------------------------------------
# 7. 報告カード（accuracy を載せない指標のセット）
# ------------------------------------------------------------------
card = report_card(y_test, plain, 0.2)
check_close("報告カードの PR-AUC", card["pr_auc"], 0.1827)
check_close("報告カードの適合率", card["precision"], 0.2489)
check_close("報告カードの再現率", card["recall"], 0.2089)
check("報告カードの陽性と予測した件数", card["n_predicted_positive"], 454)
check("報告カードの捕まえた件数", card["tp"], 113)
check("報告カードの見逃した件数", card["fn"], 428)
check("報告カードの空振りの件数", card["fp"], 341)
check_close("報告カードの Brier スコア", card["brier"], EXPECTED_BRIER["plain"], tol=BRIER_TOLERANCE)
check("報告カードに accuracy が含まれないこと", "accuracy" in card, False)

# ------------------------------------------------------------------
# 8. 練習問題の解答コード
# ------------------------------------------------------------------
q1 = q1_metric_gap.summary(y_test, plain)
check_close("問題1 の ROC AUC", q1["roc_auc"], 0.7911)
check_close("問題1 の PR-AUC", q1["pr_auc"], 0.1827)
check_close("問題1 の accuracy", q1["accuracy"], 0.9640)
check_close("問題1 の accuracy の差", q1["accuracy_gap"], 0.0, tol=1e-12)
check_close("問題1 の ROC AUC の伸び", q1["roc_gap"], 0.291)
check_close("問題1 の PR-AUC の伸び", q1["pr_gap"], 0.147)

q2 = q2_confusion_reality.report(y_test, plain)
for key, expected in EXPECTED_CONFUSION.items():
    check(f"問題2 の {key.upper()}", q2[key], expected)
check("問題2 の実際のキャンセル件数", q2["n_actual_positive"], 541)
check("問題2 の陽性と予測した件数", q2["n_predicted_positive"], 58)
check_close("問題2 の再現率", q2["recall"], 0.0536)
check_close("問題2 の 100 件あたり捕まえた件数", q2["caught_per_100"], 5.36, tol=0.05)

q3 = q3_threshold_table.choose(threshold_table(y_test, plain))
check("問題3 の条件を満たす閾値", [round(t, 2) for t in q3["allowed_thresholds"]], [0.2, 0.3, 0.5])
check("問題3 が選んだ閾値", round(q3["chosen"]["threshold"], 2), 0.2)
check("問題3 の陽性と予測した件数", q3["chosen"]["n_positive"], 454)
check_close("問題3 の再現率", q3["chosen"]["recall"], 0.2089)
check("問題3 の F1 最大の閾値", round(q3["best_f1"]["threshold"], 2), 0.1)

q4 = q4_class_weight.compare()
check_close("問題4 の balanced の ROC AUC", q4["balanced"]["roc_auc"], 0.7901)
check_close("問題4 の balanced の PR-AUC", q4["balanced"]["pr_auc"], 0.1812)
check_close("問題4 の balanced の再現率", q4["balanced"]["recall"], 0.5841)
check_close("問題4 の balanced の確率の平均", q4["balanced"]["mean_proba"], 0.2656)
check("問題4 の ROC AUC の改善判定", q4["roc_improved"], False)
check("問題4 の PR-AUC の改善判定", q4["pr_improved"], False)
check("問題4 の再現率の改善判定", q4["recall_improved"], True)
check("問題4 の Brier 悪化判定", q4["brier_worse"], True)
check_close("問題4 の確率の平均の倍率", q4["mean_ratio"], 7.5, tol=0.1)

check("問題5 の PR-AUC 改善判定", under_counts["pr_improved"], False)
check("問題5 の Brier 悪化判定", under_counts["brier_worse"], True)
check("問題5 の確率の平均が正例率に近いかの判定", under_counts["mean_close"], False)

q6 = q6_report_card.analyze()
check_close("問題6 の報告カードの PR-AUC", q6["card"]["pr_auc"], 0.1827)
check_close("問題6 の報告カードの再現率", q6["card"]["recall"], 0.2089)
check("問題6 の報告カードの捕まえた件数", q6["card"]["tp"], 113)
check_close("問題6 の重みなしのずれ", q6["plain_gap"], 0.0176, tol=TOLERANCE)
check_close("問題6 のアンダーサンプリングのずれ", q6["under_gap"], 0.7009, tol=TOLERANCE)
check("問題6 のチェックリストの項目数", len(q6_report_card.CHECKLIST), 5)

# ------------------------------------------------------------------
# 9. 全スクリプトが実行でき、図が保存され、フォントが欠けないこと
# ------------------------------------------------------------------
modules = [
    # 本文のスクリプト
    imbalance_overview,
    roc_vs_pr,
    confusion_at_default,
    threshold_sweep,
    class_weight_effect,
    undersampling,
    calibration_check,
    report_set,
    # 練習問題の解答
    q1_metric_gap,
    q2_confusion_reality,
    q3_threshold_table,
    q4_class_weight,
    q5_undersampling,
    q6_report_card,
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
print("セッション 24 のすべての検証に成功しました。")
