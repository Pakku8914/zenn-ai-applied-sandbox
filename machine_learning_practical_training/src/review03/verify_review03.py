"""横断復習③ の検証スクリプト。

「横断復習③：信じられるモデルにする ― セッション20〜28の総点検」の練習問題と解答に
載せた数値・判定・図が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/review03/verify_review03.py

注意: 「セッション23：ハイパーパラメータ探索」で測った探索の成績（グリッド 60 回・
ランダム 30 回）は、ここでは測り直しません。同じ `verify-all.sh` から実行される
`src/session23/verify_23.py` が毎回検証しており、この章で 90 回の学習をやり直すと
検証時間が数分伸びるだけだからです。
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import q7_leak_hunt
import q8_metric_report
import q9_interpretation_audit
import q10_monitoring_plan
from common import (
    CANCEL_THRESHOLDS,
    CONSTANT_GUESS,
    DATA_DIR,
    HIGH_NUMERIC,
    LGBM,
    LINEAR,
    MEAN,
    NEGATIVE_LABEL,
    OUT_DIR,
    POSITIVE_LABEL,
    PUBLISHED_YEAR_P_VALUE,
    RANDOM_ID,
    average_scores,
    best_cost_threshold,
    body_length_pair,
    cancel_bundle,
    cancel_time_split,
    confusion_parts,
    constant_prediction,
    cv_strategies,
    gbm_bundle,
    halves,
    high_bundle,
    holdout_auc,
    impurity_table,
    leak_experiments,
    load_review_table,
    majority_baseline,
    monthly_auc,
    outlier_effect,
    pdp_table,
    per_class_table,
    permutation_table,
    permutation_value,
    pipeline_bundle,
    predict_at,
    psi_table,
    quantity_drift,
    regression_scores,
    residual_by_actual,
    retrain_rules,
    score_summary,
    shap_bundle,
    shap_local_check,
    shap_mean_abs,
    should_retrain,
    star_multiclass,
    star_regression,
    star_stratify_error,
    threshold_metrics,
    trend_summary,
    unit_price_drift,
    youden_point,
)

TOLERANCE = 0.005    # 指標の許容誤差（本書共通）
TIGHT = 0.0005       # 標準偏差・差など、もともと小さい値に使う許容誤差
BRIER_TOL = 0.001    # Brier スコアは値が小さいので細かく見る
PSI_TOL = 0.002      # PSI の許容誤差

EXPECTED_COUNTS = {"n_rows": 14169, "n_train": 10626, "n_test": 3543}
# 高評価分類（ロジスティック回帰）
EXPECTED_HIGH = {"accuracy": 0.8422, "roc_auc": 0.8265, "pr_auc": 0.9554, "log_loss": 0.3592}
EXPECTED_HIGH_CONFUSION = {"tn": 162, "fp": 487, "fn": 72, "tp": 2822}
# (クラス, 適合率, 再現率, F1, 件数)
EXPECTED_PER_CLASS = [
    (NEGATIVE_LABEL, 0.6923, 0.2496, 0.3669, 649),
    (POSITIVE_LABEL, 0.8528, 0.9751, 0.9099, 2894),
]
EXPECTED_AVERAGES = {"accuracy": 0.8422, "macro_f1": 0.6384, "weighted_f1": 0.8104}
EXPECTED_YOUDEN = {"threshold": 0.8261, "tpr": 0.6755, "fpr": 0.1911}
# (見逃しの重み, 誤検出の重み) -> (総コストが最小になる閾値, その総コスト)
EXPECTED_COSTS = {(1, 1): (0.50, 559), (5, 1): (0.10, 626), (1, 5): (0.80, 1592)}
EXPECTED_MULTICLASS = {"accuracy": 0.6949, "macro_f1": 0.4305, "weighted_f1": 0.6542}
# 星の回帰（MAE / RMSE / MAPE / R2）
EXPECTED_REGRESSION = {
    LINEAR: (0.3841, 0.4735, 0.1018, 0.3582),
    LGBM: (0.3899, 0.4881, 0.1034, 0.3182),
    MEAN: (0.3614, 0.5911, 0.0984, -0.0000),
}
EXPECTED_WINNERS = {"mae": MEAN, "mape": MEAN, "rmse": LINEAR, "r2": LINEAR}
# 実測の星 -> (残差の平均, 予測の平均)
EXPECTED_RESIDUAL = {3.0: (-0.6641, 3.6641), 4.0: (0.0188, 3.9812), 5.0: (0.6558, 4.3442)}
# 交差検証（平均, 標準偏差）
EXPECTED_CV = {
    "① 層化 5 分割": (0.8240, 0.0084),
    "② 層化なし 5 分割": (0.8242, 0.0113),
    "③ 顧客単位のグループ分割": (0.8238, 0.0043),
    "④ 時系列分割": (0.8264, None),
}
EXPECTED_STRATIFIED_FOLDS = [0.8200, 0.8380, 0.8128, 0.8270, 0.8222]
EXPECTED_SERIES_FOLDS = [0.8354, 0.8203, 0.8300, 0.8272, 0.8189]
# リークの 4 実験（正しい手順, リーク, 差, 持ち上がったか）
EXPECTED_LEAKS = [
    ("① 標準化を分割前に当てる", 0.8265, 0.8265, 0.0000, False),
    ("② 雑音 500 列から分割前に選抜", 0.5086, 0.5591, 0.0505, True),
    ("③ book_id の対応表を全データで作る", 0.7809, 0.8153, 0.0344, True),
    ("④ body_length（投稿後に決まる）を使う", 0.7763, 0.8265, 0.0502, True),
]
EXPECTED_RISKY_COUNTS = [2, 2, 3, 2, 4]
# 不純度ベースの重要度（split ＝ 分割に使われた回数）
EXPECTED_SPLIT = {"body_length": 2669, "unit_price": 1327, "pages": 1161, "published_year": 576}
EXPECTED_SPLIT_TOTAL = 6000
EXPECTED_GAIN_TOP = [("unit_price", 9185), ("body_length", 8792)]
# permutation importance（評価データ・大きい順）
EXPECTED_PERM_TEST = [
    ("unit_price", 0.1908),
    ("category", 0.0969),
    ("body_length", 0.0706),
    ("pages", 0.0303),
    ("published_year", -0.0004),
]
EXPECTED_RANDOM_ID = {
    "n_columns": 10,
    "split": 1599,
    "split_rank": 2,
    "gain": 4268,
    "gain_rank": 3,
    "top_split_feature": "body_length",
    "top_split": 1644,
    "perm_test": 0.0031,
    "perm_train": 0.0940,
    "roc_auc_plain": 0.7966,
    "roc_auc_noisy": 0.7985,
}
EXPECTED_SHAP = {
    "shape": (100, 4),
    "base": 2.1601,
    "mean_abs": {"unit_price": 1.3602, "body_length": 0.5482, "pages": 0.2446, "published_year": 0.0589},
    "row0": {"unit_price": 3.0823, "body_length": 0.5170, "published_year": 0.0702, "pages": -0.2421},
    "total": 3.4274,
    "logit": 5.5874,
    "proba": 0.9963,
}
EXPECTED_PDP = {
    "unit_price": (["800", "1,508", "2,215", "2,922", "3,630"], [0.9929, 0.8705, 0.7416, 0.6885, 0.5446]),
    "body_length": (["20", "66", "112", "158", "204"], [0.9269, 0.8426, 0.7905, 0.7469, 0.6167]),
}
# キャンセル予測
EXPECTED_CANCEL_COUNTS = {"n_rows": 60031, "n_train": 45023, "n_test": 15008}
EXPECTED_CANCEL_CONFUSION = {"tn": 14438, "fp": 29, "fn": 512, "tp": 29}
# 閾値 -> (適合率, 再現率, 陽性と予測した件数, 捕まえた件数, 見逃した件数)
EXPECTED_CANCEL_THRESHOLDS = {
    0.1: (0.1612, 0.3993, 1340, 216, 325),
    0.3: (0.3545, 0.1442, 220, 78, 463),
    0.5: (0.5000, 0.0536, 58, 29, 512),
}
EXPECTED_CANCEL_KINDS = {
    "plain": {"roc_auc": 0.7911, "pr_auc": 0.1827, "mean_proba": 0.0352, "brier": 0.03235, "n_fit": 45023},
    "balanced": {"roc_auc": 0.7901, "pr_auc": 0.1812, "mean_proba": 0.2656, "brier": 0.12445, "n_fit": 45023},
    "under": {"roc_auc": 0.7857, "pr_auc": 0.1563, "mean_proba": 0.3570, "brier": 0.19322, "n_fit": 3242},
}
# 監視
EXPECTED_HALVES = {"before": 15115, "after": 42754}
EXPECTED_PSI = {"unit_price": 0.0010, "quantity": 0.0000, "discount_rate": 0.0001, "amount": 0.0027}
EXPECTED_DRIFT = [(1.00, 0.0010, "安定"), (1.05, 0.0192, "安定"), (1.20, 0.2541, "要再学習"), (1.50, 0.9056, "要再学習")]
EXPECTED_QUANTITY_DRIFT = {"n_changed": 12826, "psi_injected": 0.3059, "judgement_injected": "要再学習"}
EXPECTED_TIME_SPLIT = {"n_train": 15657, "n_test": 44374, "roc_auc": 0.7546, "pr_auc": 0.1356}
EXPECTED_MONTHLY = [
    ("2026-04", 0.7586),
    ("2026-05", 0.7259),
    ("2026-06", 0.7525),
    ("2026-07", 0.7407),
    ("2026-08", 0.7790),
    ("2026-09", 0.7661),
]
EXPECTED_TREND = {
    "mean": 0.7538,
    "std": 0.0171,
    "lower": 0.7195,
    "upper": 0.7881,
    "span": 0.0531,
    "slope": 0.0053,
}
FIGURES = ["review03_metric_report.png", "review03_monitoring.png"]

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual}")
    if not ok:
        print(f"     期待値: {expected}")
        failures.append(label)


def check_close(label: str, actual: float, expected: float, tol: float = TOLERANCE) -> None:
    ok = abs(float(actual) - expected) <= tol
    print(f"{'OK  ' if ok else 'NG  '} {label}: {float(actual):+.5f}")
    if not ok:
        print(f"     期待値: {expected:+.5f} ± {tol}")
        failures.append(label)


missing = [name for name in ("books", "customers", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. 母集団と分割（src/verify_setup.py の 5 節と同じ表・同じ並び・同じ分割）
# ------------------------------------------------------------------
df = load_review_table()
high = high_bundle()
check("学習に使うレビュー件数", high["n_rows"], EXPECTED_COUNTS["n_rows"])
check("訓練データの件数", high["n_train"], EXPECTED_COUNTS["n_train"])
check("評価データの件数", high["n_test"], EXPECTED_COUNTS["n_test"])
check("分割の合計", high["n_train"] + high["n_test"], EXPECTED_COUNTS["n_rows"])
check_close("正例率（訓練）", high["rate_train"], 0.8167, tol=0.0001)
check_close("正例率（評価）", high["rate_test"], 0.8168, tol=0.0001)

# ------------------------------------------------------------------
# 2. 分類の評価指標（セッション20）
# ------------------------------------------------------------------
for key, expected in EXPECTED_HIGH.items():
    check_close(f"高評価分類の {key}", high[key], expected)

y_test, proba = high["y_test"], high["proba"]
parts = confusion_parts(y_test, predict_at(proba))
for key, expected in EXPECTED_HIGH_CONFUSION.items():
    check(f"混同行列の {key.upper()}", parts[key], expected)
check("4 象限の合計が評価データの件数と一致すること", sum(parts.values()), EXPECTED_COUNTS["n_test"])

table = per_class_table(y_test, predict_at(proba))
for (label, precision, recall, f1, support), row in zip(EXPECTED_PER_CLASS, table.itertuples(index=False)):
    check(f"クラス {label} の件数", int(row.support), support)
    check_close(f"クラス {label} の適合率", float(row.precision), precision)
    check_close(f"クラス {label} の再現率", float(row.recall), recall)
    check_close(f"クラス {label} の F1", float(row.f1), f1)
averages = average_scores(y_test, predict_at(proba))
for key, expected in EXPECTED_AVERAGES.items():
    check_close(f"平均の取り方: {key}", averages[key], expected)
check(
    "micro F1 が accuracy と一致すること（単一ラベルの分類）",
    bool(abs(averages["micro_f1"] - averages["accuracy"]) < 1e-12),
    True,
)
check("macro F1 が weighted F1 より低いこと", bool(averages["macro_f1"] < averages["weighted_f1"]), True)

base_high = majority_baseline(y_test, POSITIVE_LABEL)
check_close("ベースライン（全部「高評価」）の accuracy", base_high["accuracy"], 0.8168, tol=0.0001)
check_close("ベースラインの ROC AUC", base_high["roc_auc"], 0.5000, tol=0.0001)
check("accuracy の改善幅の表示（ポイント）", f"{(high['accuracy'] - base_high['accuracy']) * 100:.1f}", "2.5")

youden = youden_point(y_test, proba)
for key, expected in EXPECTED_YOUDEN.items():
    check_close(f"Youden の {key}", youden[key], expected)
for (miss, alarm), (threshold, cost) in EXPECTED_COSTS.items():
    row = best_cost_threshold(y_test, proba, miss, alarm)
    check_close(f"コスト {miss}:{alarm} の最適な閾値", row["threshold"], threshold, tol=1e-6)
    check(f"コスト {miss}:{alarm} の総コスト", int(row["total_cost"]), cost)

message = star_stratify_error()
check("多クラスで層化しようとすると ValueError になること", "least populated" in message, True)
multiclass = star_multiclass()
for key, expected in EXPECTED_MULTICLASS.items():
    check_close(f"多クラス（星 1〜5）の {key}", multiclass[key], expected)
check(
    "多クラスでは macro F1 と weighted F1 の差が 0.2 を超えること",
    bool(multiclass["weighted_f1"] - multiclass["macro_f1"] > 0.2),
    True,
)

# ------------------------------------------------------------------
# 3. 回帰の評価指標（セッション21）
# ------------------------------------------------------------------
regression = star_regression()
for name, (mae, rmse, mape, r2) in EXPECTED_REGRESSION.items():
    scores = regression["scores"][name]
    check_close(f"{name} の MAE", scores["mae"], mae)
    check_close(f"{name} の RMSE", scores["rmse"], rmse)
    check_close(f"{name} の MAPE", scores["mape"], mape)
    check_close(f"{name} の R2", scores["r2"], r2)
check("MAE で 1 位になるモデル", min(regression["scores"], key=lambda n: regression["scores"][n]["mae"]), EXPECTED_WINNERS["mae"])
check("RMSE で 1 位になるモデル", min(regression["scores"], key=lambda n: regression["scores"][n]["rmse"]), EXPECTED_WINNERS["rmse"])
check("R2 で 1 位になるモデル", max(regression["scores"], key=lambda n: regression["scores"][n]["r2"]), EXPECTED_WINNERS["r2"])
check(
    "MAE の 1 位と RMSE の 1 位が違うこと",
    EXPECTED_WINNERS["mae"] != EXPECTED_WINNERS["rmse"],
    True,
)
check("平均予測の R2 がわずかに負であること", bool(-0.001 < regression["scores"][MEAN]["r2"] < 0), True)

guess = regression_scores(regression["y_test"], constant_prediction(regression["y_test"], CONSTANT_GUESS))
check_close("全部 3.0 と答えたときの R2", guess["r2"], -2.6921)
check("全部 3.0 の R2 が負であること", bool(guess["r2"] < 0), True)

grouped = residual_by_actual(regression["y_test"], regression["preds"][LGBM])
for star, (residual, pred_mean) in EXPECTED_RESIDUAL.items():
    check_close(f"実測 星 {star:.0f} の残差の平均", float(grouped.loc[star, "residual_mean"]), residual)
    check_close(f"実測 星 {star:.0f} に対する予測の平均", float(grouped.loc[star, "pred_mean"]), pred_mean)
check(
    "星 3 は高めに・星 5 は低めに外していること（両端で平均に引き寄せられる）",
    bool(grouped.loc[3.0, "residual_mean"] < 0 < grouped.loc[5.0, "residual_mean"]),
    True,
)

outlier = outlier_effect(regression["y_test"], regression["preds"][LGBM])
check_close("差し替え前の MAE", outlier["before"]["mae"], 0.3899)
check_close("差し替え後の MAE", outlier["after"]["mae"], 0.3913)
check_close("差し替え前の RMSE", outlier["before"]["rmse"], 0.4881)
check_close("差し替え後の RMSE", outlier["after"]["rmse"], 0.4967)
check(
    "RMSE の増え方が MAE の増え方の 5 倍を超えること",
    bool(
        (outlier["after"]["rmse"] - outlier["before"]["rmse"])
        > (outlier["after"]["mae"] - outlier["before"]["mae"]) * 5
    ),
    True,
)

# ------------------------------------------------------------------
# 4. 交差検証と分割の型（セッション22）
# ------------------------------------------------------------------
rows = cv_strategies()
check("比べた分割の数", len(rows), 4)
for row in rows:
    mean, std = EXPECTED_CV[row["label"]]
    check_close(f"{row['label']} の平均", row["mean"], mean)
    if std is not None:
        check_close(f"{row['label']} の標準偏差", row["std"], std, tol=TIGHT)
for number, expected in enumerate(EXPECTED_STRATIFIED_FOLDS, start=1):
    check_close(f"層化 5 分割の fold {number}", rows[0]["scores"][number - 1], expected)
for number, expected in enumerate(EXPECTED_SERIES_FOLDS, start=1):
    check_close(f"時系列分割の fold {number}", rows[3]["scores"][number - 1], expected)
check("層化なしのほうがばらつきが大きいこと", bool(rows[1]["std"] > rows[0]["std"]), True)
check("グループ分割がいちばんばらつきが小さいこと", bool(rows[2]["std"] < rows[0]["std"]), True)
check(
    "4 つの分割の平均がすべて許容誤差の中に収まること",
    bool(max(row["mean"] for row in rows) - min(row["mean"] for row in rows) < TOLERANCE),
    True,
)
holdout = holdout_auc(df)
check_close("ホールドアウト 1 回の ROC AUC", holdout, 0.8265)
check_close("ホールドアウト − 交差検証の平均", holdout - rows[0]["mean"], 0.0025, tol=0.001)
check(
    "ホールドアウトが fold の最小〜最大の中に入ること",
    bool(min(rows[0]["scores"]) <= holdout <= max(rows[0]["scores"])),
    True,
)
counts = df["customer_id"].value_counts()
check("顧客の人数", int(counts.size), 5807)
check("1 顧客あたりの最大レビュー数", int(counts.max()), 15)

# ------------------------------------------------------------------
# 5. Pipeline（セッション25）
# ------------------------------------------------------------------
pipeline = pipeline_bundle()
check("変換後の列数（数値 4 列 + カテゴリ 3 列）", len(pipeline["names"]), 20)
check("region の欠損数", pipeline["n_missing_region"], 729)
check_close("Pipeline のテスト AUC", pipeline["test_auc"], 0.8265)
check_close("Pipeline の交差検証の平均", pipeline["cv_mean"], 0.8232)
check_close("Pipeline の交差検証の標準偏差", pipeline["cv_std"], 0.0083, tol=TIGHT)

# ------------------------------------------------------------------
# 6. リークの 4 実験（セッション13・22・実装 7）
# ------------------------------------------------------------------
leaks = leak_experiments()
check("比べた実験の数", len(leaks), 4)
for row, (label, correct, leaked, gap, fooled) in zip(leaks, EXPECTED_LEAKS):
    check(f"実験の並び: {label}", row["label"], label)
    check_close(f"{label} の正しい手順", row["correct"], correct)
    check_close(f"{label} のリークした手順", row["leaked"], leaked)
    check_close(f"{label} の差", row["gap"], gap, tol=TIGHT if gap == 0.0 else TOLERANCE)
    check(f"{label} は持ち上がったか", row["fooled"], fooled)
check("許容誤差を超えて持ち上がった実験の数", sum(1 for row in leaks if row["fooled"]), 3)
check("雑音の列の形", leaks[1]["shape"], (14169, 500))
check(
    "雑音から選んだ 10 列は、正しい手順なら当て推量とほぼ同じになること",
    bool(abs(leaks[1]["correct"] - 0.5) < 0.01),
    True,
)
body = body_length_pair(df)
check_close("body_length と rating の相関", body["corr"], -0.2867)
check("body_length を外すと下がること", bool(body["correct"] < body["leaked"]), True)

# ------------------------------------------------------------------
# 7. 3 種類の重要度と SHAP（セッション26・実装 9）
# ------------------------------------------------------------------
impurity = impurity_table()
split_map = dict(zip(impurity["feature"], impurity["split"].astype("int64")))
for name, expected in EXPECTED_SPLIT.items():
    check(f"split: {name}", int(split_map[name]), expected)
check("split の合計（木 200 本 × 1 本あたり 30 分割）", int(impurity["split"].sum()), EXPECTED_SPLIT_TOTAL)
gain_sorted = impurity.sort_values("gain", ascending=False)
for rank, (name, expected) in enumerate(EXPECTED_GAIN_TOP, start=1):
    check(f"gain {rank} 位の列", str(gain_sorted.iloc[rank - 1]["feature"]), name)
    check(f"gain {rank} 位の値（int で切り捨て）", int(gain_sorted.iloc[rank - 1]["gain"]), expected)
check(
    "split と gain で 1 位が入れ替わること",
    str(impurity.sort_values("split", ascending=False).iloc[0]["feature"]) != EXPECTED_GAIN_TOP[0][0],
    True,
)

perm = permutation_table("test")
check("permutation の行数（category は 1 行にまとまる）", len(perm), 5)
for rank, (name, expected) in enumerate(EXPECTED_PERM_TEST, start=1):
    check(f"permutation（評価）{rank} 位の列", str(perm.iloc[rank - 1]["feature"]), name)
    check_close(f"permutation（評価）{name}", float(perm.iloc[rank - 1]["mean"]), expected)
check(
    "published_year の permutation が負であること（シャッフルしても落ちない）",
    bool(permutation_value("published_year", "test") < 0),
    True,
)
check_close("引用している p 値（セッション16）", PUBLISHED_YEAR_P_VALUE, 0.2425)

audit = q9_interpretation_audit.random_id_audit()
for key, expected in EXPECTED_RANDOM_ID.items():
    if isinstance(expected, str):
        check(f"random_id の {key}", audit[key], expected)
    elif isinstance(expected, int):
        check(f"random_id の {key}", int(audit[key]), expected)
    else:
        check_close(f"random_id の {key}", audit[key], expected)
check(
    "random_id を足しても ROC AUC が許容誤差の中でしか動かないこと",
    bool(abs(audit["roc_auc_noisy"] - audit["roc_auc_plain"]) < TOLERANCE),
    True,
)
check(
    "評価データの permutation が訓練データより 1 桁小さいこと",
    bool(audit["perm_test"] * 10 < audit["perm_train"]),
    True,
)
check("random_id を足した後の特徴量の数", len(gbm_bundle(True)["features"]), 6)
check("random_id が数値列の末尾にあること", gbm_bundle(True)["numeric"][-1], RANDOM_ID)

shap_data = shap_bundle()
check("shap_values の形", shap_data["values"].shape, EXPECTED_SHAP["shape"])
check_close("expected_value（基準値）", shap_data["base"], EXPECTED_SHAP["base"])
check("TreeExplainer の警告が捕まえられていること", shap_data["warnings"][:1], ["UserWarning"])
mean_abs = dict(zip(shap_mean_abs()["feature"], shap_mean_abs()["mean_abs"]))
for name, expected in EXPECTED_SHAP["mean_abs"].items():
    check_close(f"SHAP の平均絶対値 {name}", float(mean_abs[name]), expected)
check("SHAP の平均絶対値の 1 位", str(shap_mean_abs().iloc[0]["feature"]), "unit_price")
local = shap_local_check(0)
for name, expected in EXPECTED_SHAP["row0"].items():
    check_close(f"1 行目の SHAP 値 {name}", local["values"][name], expected)
check_close("SHAP 値の合計", local["total"], EXPECTED_SHAP["total"])
check_close("合計 ＋ 基準値（対数オッズ）", local["logit"], EXPECTED_SHAP["logit"])
check_close("シグモイドで確率に直した値", local["proba_from_shap"], EXPECTED_SHAP["proba"])
check_close("predict_proba の値", local["proba_from_model"], EXPECTED_SHAP["proba"])
check("加法性が成り立つこと（差が 1e-6 未満）", local["matches"], True)
check("SHAP の分解が数値 4 列ぶんあること", len(local["values"]), len(HIGH_NUMERIC))

for feature, (grid_text, averages_expected) in EXPECTED_PDP.items():
    pdp = pdp_table(feature)
    check(f"{feature} の部分依存のグリッド", [f"{value:,.0f}" for value in pdp["grid"]], grid_text)
    for index, expected in enumerate(averages_expected):
        check_close(f"{feature} の部分依存 {index + 1} 番目", float(pdp["average"].iloc[index]), expected)
    check(
        f"{feature} は値が大きくなるほど確率が下がること",
        bool(pdp["average"].iloc[0] > pdp["average"].iloc[-1]),
        True,
    )

# ------------------------------------------------------------------
# 8. 不均衡データ（セッション24・実装 8）
# ------------------------------------------------------------------
cancel = cancel_bundle("plain")
for key, expected in EXPECTED_CANCEL_COUNTS.items():
    check(f"キャンセル予測の {key}", cancel[key], expected)
yc, pc = cancel["y_test"], cancel["proba"]
base_cancel = majority_baseline(yc, NEGATIVE_LABEL)
check_close("キャンセル率（評価データ）", base_cancel["positive_rate"], 0.0360, tol=0.0001)
check("評価データのキャンセル件数", base_cancel["n_positive"], 541)
check_close("ベースライン（全部「しない」）の accuracy", base_cancel["accuracy"], 0.9640, tol=0.0001)

cancel_parts = confusion_parts(yc, predict_at(pc))
for key, expected in EXPECTED_CANCEL_CONFUSION.items():
    check(f"キャンセル予測の混同行列 {key.upper()}", cancel_parts[key], expected)
check("陽性と予測した件数（FP + TP）", cancel_parts["fp"] + cancel_parts["tp"], 58)

for threshold in CANCEL_THRESHOLDS:
    precision, recall, n_positive, tp, fn = EXPECTED_CANCEL_THRESHOLDS[threshold]
    row = threshold_metrics(yc, pc, threshold)
    check_close(f"閾値 {threshold} の適合率", row["precision"], precision)
    check_close(f"閾値 {threshold} の再現率", row["recall"], recall)
    check(f"閾値 {threshold} の陽性と予測した件数", row["n_positive"], n_positive)
    check(f"閾値 {threshold} の捕まえた件数", row["tp"], tp)
    check(f"閾値 {threshold} の見逃した件数", row["fn"], fn)

for kind, expected in EXPECTED_CANCEL_KINDS.items():
    bundle = cancel_bundle(kind)
    scores = score_summary(yc, bundle["proba"])
    check(f"{kind} の学習件数", bundle["n_fit"], expected["n_fit"])
    check_close(f"{kind} の ROC AUC", scores["roc_auc"], expected["roc_auc"])
    check_close(f"{kind} の PR-AUC", scores["pr_auc"], expected["pr_auc"])
    check_close(f"{kind} の予測確率の平均", scores["mean_proba"], expected["mean_proba"])
    check_close(f"{kind} の Brier スコア", scores["brier"], expected["brier"], tol=BRIER_TOL)
plain_scores = score_summary(yc, pc)
check_close("重みなしの accuracy", plain_scores["accuracy"], 0.9640, tol=0.0001)
check(
    "accuracy がベースラインと同じ値になること",
    bool(abs(plain_scores["accuracy"] - base_cancel["accuracy"]) < 1e-9),
    True,
)
check("ROC AUC が PR-AUC より大きいこと", bool(plain_scores["roc_auc"] > plain_scores["pr_auc"]), True)
check(
    "重みを付けると Brier スコアが悪化すること",
    bool(score_summary(yc, cancel_bundle("balanced")["proba"])["brier"] > plain_scores["brier"]),
    True,
)

# ------------------------------------------------------------------
# 9. 監視（セッション28・実装 10）
# ------------------------------------------------------------------
parts_halves = halves()
check("前半（〜2025-08）の有効注文", len(parts_halves["before"]), EXPECTED_HALVES["before"])
check("後半（2025-09〜）の有効注文", len(parts_halves["after"]), EXPECTED_HALVES["after"])

psi = psi_table()
psi_map = dict(zip(psi["column"], psi["psi"]))
for name, expected in EXPECTED_PSI.items():
    check_close(f"PSI: {name}", float(psi_map[name]), expected, tol=PSI_TOL)
check("PSI の判定がすべて「安定」であること", sorted(set(psi["judgement"])), ["安定"])

drift = unit_price_drift()
for (ratio, expected, judgement), row in zip(EXPECTED_DRIFT, drift.itertuples(index=False)):
    check_close(f"単価 {ratio:.2f} 倍の PSI", float(row.psi), expected, tol=PSI_TOL)
    check(f"単価 {ratio:.2f} 倍の判定", str(row.judgement), judgement)
quantity = quantity_drift()
check("差し替えた注文の件数", quantity["n_changed"], EXPECTED_QUANTITY_DRIFT["n_changed"])
check_close("数量を差し替えたあとの PSI", quantity["psi_injected"], EXPECTED_QUANTITY_DRIFT["psi_injected"], tol=PSI_TOL)
check("数量を差し替えたあとの判定", quantity["judgement_injected"], EXPECTED_QUANTITY_DRIFT["judgement_injected"])

split = cancel_time_split()
check("時間分割の学習件数", split["n_train"], EXPECTED_TIME_SPLIT["n_train"])
check("時間分割の評価件数", split["n_test"], EXPECTED_TIME_SPLIT["n_test"])
check("学習データの最終日", str(split["train_end"].date()), "2025-08-31")
check_close("時間分割の ROC AUC", split["roc_auc"], EXPECTED_TIME_SPLIT["roc_auc"])
check_close("時間分割の PR-AUC", split["pr_auc"], EXPECTED_TIME_SPLIT["pr_auc"])
check("無作為分割（0.7911）より低いこと", bool(split["roc_auc"] < 0.7911), True)

monthly = monthly_auc()
check("月次の行数", len(monthly), len(EXPECTED_MONTHLY))
for (month, expected), row in zip(EXPECTED_MONTHLY, monthly.itertuples(index=False)):
    check(f"月次の並び: {month}", str(row.month), month)
    check_close(f"月次 ROC AUC（{month}）", float(row.roc_auc), expected)
trend = trend_summary(monthly)
TREND_TOLERANCES = {"mean": TOLERANCE, "std": TIGHT, "lower": TOLERANCE, "upper": TOLERANCE, "span": TIGHT, "slope": TIGHT}
for key, expected in EXPECTED_TREND.items():
    check_close(f"月次 AUC の {key}", trend[key], expected, tol=TREND_TOLERANCES[key])
check("下限を下回った月の数", trend["n_below"], 0)
check("2 か月連続で下回っていないこと", trend["consecutive_below"], False)
check("下降トレンドと判定されないこと", trend["declining"], False)

rules = retrain_rules()
check("判断基準の数", len(rules), 4)
check("条件の名前", [str(rule["name"]) for rule in rules], ["データドリフト", "性能の低下", "時間の経過", "データ量の増加"])
check("発火のしかた", [bool(rule["fire"]) for rule in rules], [False, False, True, True])
check("時間の経過の実測", str(rules[2]["actual"]), "366 日")
check("データ量の増加の実測", str(rules[3]["actual"]), "3.83 倍")
decision = should_retrain(rules)
check("再学習するかどうか", decision["retrain"], True)
check("発火した条件", decision["fired"], ["時間の経過", "データ量の増加"])

# ------------------------------------------------------------------
# 10. 解答スクリプトの構造（問題文と解答の対応）
# ------------------------------------------------------------------
check("問題7 のチェック項目の数", len(q7_leak_hunt.CHECKS), 5)
check("問題7 の直し方の数", len(q7_leak_hunt.FIXES), 5)
specs = q7_leak_hunt.build_specs(leaks, "顧客 5,807 人 / レビュー 14,169 件 / 最大 15 件")
check("問題7 で監査する設計の数", len(specs), 5)
risky_counts = [sum(1 for row in q7_leak_hunt.audit(spec) if row["risky"]) for spec in specs]
check("要確認の件数（①〜⑤）", risky_counts, EXPECTED_RISKY_COUNTS)
check(
    "② は「うますぎる改善幅」では捕まらないこと（Q3 で捕まえる）",
    [row["risky"] for row in q7_leak_hunt.audit(specs[1])][-1],
    False,
)
check(
    "⑤ は「うますぎる改善幅」で捕まること",
    [row["risky"] for row in q7_leak_hunt.audit(specs[4])][-1],
    True,
)

check("問題8 で直す報告文の数", len(q8_metric_report.WRONG_CLAIMS), 3)
fixed_claims = q8_metric_report.rewrite(q8_metric_report.cancel_report(), q8_metric_report.regression_report())
check("問題8 の書き直した文の数", len(fixed_claims), 3)
check("問題8 の (1) に PR-AUC の値が入っていること", "0.1827" in fixed_claims[0], True)
check("問題8 の (2) に平均予測の MAE が入っていること", "0.3614" in fixed_claims[1], True)
check("問題8 の (3) に閾値 0.1 の再現率が入っていること", "0.3993" in fixed_claims[2], True)

check("問題9 で直す主張の数", len(q9_interpretation_audit.WRONG_CLAIMS), 3)
judge = q9_interpretation_audit.judge_table()
check("問題9 の判定表の行数", len(judge), 3)
check("問題9 で body_length が「結果の一部」と判定されること", judge[1]["is_outcome"], "はい")
check("問題9 で published_year が「施策で動かせない」と判定されること", judge[2]["can_act"], "いいえ")
check("問題9 で published_year が「効いていると言えない」と判定されること", judge[2]["solid"], "いいえ")
check("問題9 で unit_price が「効いている」と判定されること", judge[0]["solid"], "はい")

check("問題10 の監視項目の数", len(q10_monitoring_plan.MONITORING_PLAN), 5)
check(
    "問題10 の監視項目に「測り方・頻度・注意の線・発火の線・発火したら」がそろっていること",
    sorted(q10_monitoring_plan.MONITORING_PLAN[0]),
    ["act", "how", "then", "watch", "what", "when"],
)

# ------------------------------------------------------------------
# 11. 解答スクリプトが最後まで動き、図が保存されること
# ------------------------------------------------------------------
for name in FIGURES:
    (Path(OUT_DIR) / name).unlink(missing_ok=True)  # 「前回の残り」を合格にしない

modules = [q7_leak_hunt, q8_metric_report, q9_interpretation_audit, q10_monitoring_plan]
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

for name in FIGURES:
    path = Path(OUT_DIR) / name
    size = path.stat().st_size if path.exists() else 0
    print(f"---  {name}: {size:,} バイト")
    check(f"{name} が保存され、サイズが 0 より大きいこと", size > 0, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("横断復習③ のすべての検証に成功しました。")
