"""セッション 21 の検証スクリプト。

「セッション21：回帰の評価指標」の本文・練習問題・解答に載せた数値と挙動が、
いまこの環境で再現できるかを確認します。期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session21/verify_21.py
"""

from __future__ import annotations

import contextlib
import importlib
import io
import inspect
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
from sklearn.metrics import (
    mean_absolute_percentage_error,
    mean_squared_error,
    r2_score,
    root_mean_squared_error,
)

from common import (
    CONSTANT_GUESS,
    DATA_DIR,
    LGBM,
    LINEAR,
    MEAN,
    OUT_DIR,
    OUTLIER_STAR,
    STARS,
    TARGET,
    best_model,
    constant_prediction,
    fit_predict_all,
    load_rated_reviews,
    make_toy,
    regression_scores,
    residual_by_actual,
    residual_summary,
    residuals,
    score_all,
    split_xy,
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
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:+.4f}")
    if not ok:
        print(f"     期待値: {expected:+.4f} ± {tol}")
        failures.append(label)


missing = [name for name in ("books", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. データと分割（分類の章とまったく同じ表・同じ分割条件）
# ------------------------------------------------------------------
df = load_rated_reviews()
check("星が入っているレビューの件数", len(df), 14169)
check("unit_price の欠損数", int(df["unit_price"].isna().sum()), 0)

X_train, X_test, y_train, y_test = split_xy(df)
check("訓練データの件数", len(X_train), 10626)
check("評価データの件数", len(X_test), 3543)
check_close("星の平均（全体）", float(df[TARGET].mean()), 3.9725)
check_close("星の標準偏差（全体）", float(df[TARGET].std(ddof=0)), 0.5914)
check_close("星の中央値（全体）", float(df[TARGET].median()), 4.0)
check(
    "星の分布",
    {int(star): int(count) for star, count in df[TARGET].value_counts().sort_index().items()},
    {1: 1, 2: 38, 3: 2558, 4: 9325, 5: 2247},
)

# ------------------------------------------------------------------
# 2. 手計算できる 5 件（同じ MAE でも RMSE・MAPE の順位が変わる）
# ------------------------------------------------------------------
toy = make_toy()
toy_a = regression_scores(toy["actual"], toy["model_a"])
toy_b = regression_scores(toy["actual"], toy["model_b"])
check_close("練習データ モデルA の MAE", toy_a["mae"], 0.4000)
check_close("練習データ モデルB の MAE", toy_b["mae"], 0.4000)
check("練習データ 2 つの MAE が同じか", abs(toy_a["mae"] - toy_b["mae"]) < 1e-12, True)
check_close("練習データ モデルA の RMSE", toy_a["rmse"], 0.4472)
check_close("練習データ モデルB の RMSE", toy_b["rmse"], 0.8944)
check_close("練習データ モデルA の MAPE", toy_a["mape"], 0.1033)
check_close("練習データ モデルB の MAPE", toy_b["mape"], 0.1000)
check_close("練習データ モデルA の R2", toy_a["r2"], 0.5000)
check_close("練習データ モデルB の R2", toy_b["r2"], -1.0000)
check("練習データ RMSE で勝つのは A か", toy_a["rmse"] < toy_b["rmse"], True)
check("練習データ MAPE で勝つのは B か", toy_b["mape"] < toy_a["mape"], True)

# ------------------------------------------------------------------
# 3. 星の回帰（3 モデル × 4 指標 = 12 値）
# ------------------------------------------------------------------
y_test, preds = fit_predict_all(df)
scores = score_all(y_test, preds)

check_close("線形回帰の MAE", scores[LINEAR]["mae"], 0.3841)
check_close("線形回帰の RMSE", scores[LINEAR]["rmse"], 0.4735)
check_close("線形回帰の MAPE", scores[LINEAR]["mape"], 0.1018)
check_close("線形回帰の R2", scores[LINEAR]["r2"], 0.3582)

check_close("LightGBM の MAE", scores[LGBM]["mae"], 0.3899)
check_close("LightGBM の RMSE", scores[LGBM]["rmse"], 0.4881)
check_close("LightGBM の MAPE", scores[LGBM]["mape"], 0.1034)
check_close("LightGBM の R2", scores[LGBM]["r2"], 0.3182)

check_close("平均予測の MAE", scores[MEAN]["mae"], 0.3614)
check_close("平均予測の RMSE", scores[MEAN]["rmse"], 0.5911)
check_close("平均予測の MAPE", scores[MEAN]["mape"], 0.0984)
check_close("平均予測の R2", scores[MEAN]["r2"], -0.0000)

check("平均予測が返すのは 1 種類の値だけか", int(np.unique(preds[MEAN]).size), 1)
check("平均予測の定数（小数第 2 位）", round(float(preds[MEAN][0]), 2), 3.97)
check_close("平均予測の定数が訓練データの平均と一致すること", float(preds[MEAN][0]), float(y_train.mean()), tol=1e-9)

# この章の山場: 指標を 1 つしか見ないと結論が逆になる
check("MAE の 1 位", best_model(scores, "mae"), MEAN)
check("MAPE の 1 位", best_model(scores, "mape"), MEAN)
check("RMSE の 1 位", best_model(scores, "rmse"), LINEAR)
check("R2 の 1 位", best_model(scores, "r2"), LINEAR)
check("MAE では平均予測が LightGBM に勝つか", scores[MEAN]["mae"] < scores[LGBM]["mae"], True)
check("MAE では平均予測が線形回帰にも勝つか", scores[MEAN]["mae"] < scores[LINEAR]["mae"], True)
check("RMSE では平均予測が最下位か", scores[MEAN]["rmse"] > max(scores[LINEAR]["rmse"], scores[LGBM]["rmse"]), True)
for name in (LINEAR, LGBM, MEAN):
    check(f"{name}: MAE <= RMSE か", scores[name]["mae"] <= scores[name]["rmse"], True)

# ------------------------------------------------------------------
# 4. R2 が負になる例（全部 3.0 と答えるモデル）
# ------------------------------------------------------------------
guess = constant_prediction(y_test, CONSTANT_GUESS)
guess_scores = regression_scores(y_test, guess)
check_close("全部 3.0 の R2", guess_scores["r2"], -2.6921)
check_close("全部 3.0 の MAE", guess_scores["mae"], 0.9754)
check("全部 3.0 の R2 は負か", guess_scores["r2"] < 0, True)

ss_res = float(np.sum((y_test.to_numpy(dtype="float64") - guess) ** 2))
ss_tot = float(np.sum((y_test.to_numpy(dtype="float64") - y_test.mean()) ** 2))
check_close("定義どおりに計算した全部 3.0 の R2", 1.0 - ss_res / ss_tot, guess_scores["r2"], tol=1e-9)
on_test_mean = constant_prediction(y_test, float(y_test.mean()))
check_close("評価データの平均を返した場合の R2（ぴったり 0）", r2_score(y_test, on_test_mean), 0.0, tol=1e-9)
check(
    "平均予測（訓練データの平均）の R2 がわずかに負か",
    -0.001 < scores[MEAN]["r2"] < 0,
    True,
)
mae_of_4 = regression_scores(y_test, constant_prediction(y_test, 4.0))["mae"]
check("MAE は中央値 4.0 の定数がいちばん小さいか", mae_of_4 < scores[MEAN]["mae"], True)

# ------------------------------------------------------------------
# 5. 残差（実測 − 予測）の要約と、星ごとの系統的な偏り
# ------------------------------------------------------------------
res = residuals(y_test, preds[LGBM])
summary = residual_summary(res)
check_close("LightGBM の残差の平均", summary["mean"], -0.0088)
check_close("LightGBM の残差の標準偏差", summary["std"], 0.4880)
check_close("LightGBM の残差の最大絶対値", summary["max_abs"], 1.5971)
check_close(
    "残差の二乗平均の平方根が RMSE と一致すること",
    float(np.sqrt(np.mean(res**2))),
    scores[LGBM]["rmse"],
    tol=1e-9,
)

grouped = residual_by_actual(y_test, preds[LGBM])
check_close("実測 星 3 の残差の平均", float(grouped.loc[3.0, "residual_mean"]), -0.6641)
check_close("実測 星 4 の残差の平均", float(grouped.loc[4.0, "residual_mean"]), 0.0188)
check_close("実測 星 5 の残差の平均", float(grouped.loc[5.0, "residual_mean"]), 0.6558)
check_close("実測 星 3 に対する予測の平均", float(grouped.loc[3.0, "pred_mean"]), 3.6641)
check_close("実測 星 4 に対する予測の平均", float(grouped.loc[4.0, "pred_mean"]), 3.9812)
check_close("実測 星 5 に対する予測の平均", float(grouped.loc[5.0, "pred_mean"]), 4.3442)
check_close(
    "星 5 と星 3 に対する予測の平均の差",
    float(grouped.loc[5.0, "pred_mean"] - grouped.loc[3.0, "pred_mean"]),
    0.6801,
)
check(
    "星 3 は低め・星 5 は高めに外していること（両端で平均に引き寄せられる）",
    bool(grouped.loc[3.0, "residual_mean"] < 0 < grouped.loc[5.0, "residual_mean"]),
    True,
)

# ------------------------------------------------------------------
# 6. 予測の広がり（実測より狭い＝中央に寄せている）
# ------------------------------------------------------------------
actual_values = y_test.to_numpy(dtype="float64")
pred_values = preds[LGBM]
check("予測のばらつきは実測より小さいか", bool(pred_values.std() < actual_values.std()), True)
check(
    "予測の幅は実測の幅より狭いか",
    bool((pred_values.max() - pred_values.min()) < (actual_values.max() - actual_values.min())),
    True,
)

# ------------------------------------------------------------------
# 7. 外れ値 1 件の影響（RMSE のほうが敏感）
# ------------------------------------------------------------------
y_outlier = y_test.copy()
y_outlier.iloc[0] = OUTLIER_STAR
after = regression_scores(y_outlier, preds[LGBM])
check_close("差し替え前の RMSE", scores[LGBM]["rmse"], 0.4881)
check_close("差し替え後の RMSE", after["rmse"], 0.4967)
check_close("差し替え前の MAE", scores[LGBM]["mae"], 0.3899)
check_close("差し替え後の MAE", after["mae"], 0.3913)
mae_delta = after["mae"] - scores[LGBM]["mae"]
rmse_delta = after["rmse"] - scores[LGBM]["rmse"]
check("RMSE の増え方が MAE より大きいか", rmse_delta > mae_delta, True)
check("RMSE の増え方は MAE の 3 倍以上か", rmse_delta > mae_delta * 3, True)
check("MAE の増加は元の値の 1% 未満か", mae_delta / scores[LGBM]["mae"] < 0.01, True)

# ------------------------------------------------------------------
# 8. 指標を計算する道具の挙動（本文の「よくあるエラー」の裏付け）
# ------------------------------------------------------------------
check_close(
    "root_mean_squared_error と sqrt(mean_squared_error) が一致すること",
    float(root_mean_squared_error(y_test, preds[LGBM])),
    float(np.sqrt(mean_squared_error(y_test, preds[LGBM]))),
    tol=1e-12,
)
check("mean_squared_error に squared 引数が無いこと", "squared" in inspect.signature(mean_squared_error).parameters, False)
try:
    mean_squared_error(y_test, preds[LGBM], squared=False)
    raised = "例外なし"
except TypeError as exc:
    raised = type(exc).__name__
check("squared=False で呼んだときの例外の型", raised, "TypeError")

swapped = float(r2_score(preds[LGBM], y_test))  # 引数の順番を間違えた場合
check("r2_score の引数を逆にすると値が変わること", abs(swapped - scores[LGBM]["r2"]) > 0.01, True)

y_zero = y_test.copy()
y_zero.iloc[0] = 0.0
check(
    "実測に 0 があると MAPE が極端に大きくなること",
    float(mean_absolute_percentage_error(y_zero, preds[LGBM])) > 1e6,
    True,
)

y_nan = y_test.copy()
y_nan.iloc[0] = np.nan
try:
    r2_score(y_nan, preds[LGBM])
    nan_error = "例外なし"
except ValueError as exc:
    nan_error = type(exc).__name__
check("欠損が混ざった y で r2_score を呼んだときの例外の型", nan_error, "ValueError")

# ------------------------------------------------------------------
# 9. 本文・練習問題のスクリプトが動き、図が保存されること
# ------------------------------------------------------------------
OUT_DIR.mkdir(parents=True, exist_ok=True)
FIGURES = [
    "s21_residual_plot.png",
    "s21_pred_vs_actual.png",
    "s21_outlier_effect.png",
    "s21_q4_residual_hist.png",
    "s21_q6_pred_vs_actual.png",
]
SCRIPTS = [
    "toy_metrics",
    "compare_models",
    "r2_negative",
    "residual_plot",
    "pred_vs_actual",
    "outlier_effect",
    "metric_report",
    "q1_metrics_by_hand",
    "q2_model_metric_table",
    "q3_negative_r2",
    "q4_residual_diagnosis",
    "q5_outlier_sensitivity",
    "q6_metric_choice",
]
executed: list[str] = []
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        for name in SCRIPTS:
            importlib.import_module(name).main()  # 例外が出ればここで検証が止まる
            executed.append(name)
    glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("例外なく動いたスクリプトの数", len(executed), len(SCRIPTS))
check("日本語フォントの欠落警告の数", len(glyph_warnings), 0)
for name in FIGURES:
    path = OUT_DIR / name
    check(f"図 {name} が保存されていること", path.exists() and path.stat().st_size > 0, True)

# ------------------------------------------------------------------
# 10. 練習問題の解答コードが、本文と同じ数値を出すこと
# ------------------------------------------------------------------
q1 = importlib.import_module("q1_metrics_by_hand")
hand_a = q1.metrics_by_hand(toy["actual"], toy["model_a"])
hand_real = q1.metrics_by_hand(y_test, preds[LGBM])
check_close("問題1 自作 MAE（モデルA）", hand_a["mae"], 0.4000)
check_close("問題1 自作 RMSE（モデルA）", hand_a["rmse"], 0.4472)
check_close("問題1 自作 MAPE（モデルA）", hand_a["mape"], 0.1033)
check_close("問題1 自作 R2（モデルA）", hand_a["r2"], 0.5000)
check("問題1 自作と sklearn が一致すること（練習データ）", q1.same_values(hand_a, toy_a), True)
check(
    "問題1 自作と sklearn が一致すること（星の回帰）",
    q1.same_values(hand_real, scores[LGBM], tol=1e-10),
    True,
)

q2 = importlib.import_module("q2_model_metric_table")
check("問題2 MAE の 1 位と最下位", q2.ranking(scores, "mae"), (MEAN, LGBM))
check("問題2 RMSE の 1 位と最下位", q2.ranking(scores, "rmse"), (LINEAR, MEAN))
check("問題2 MAPE の 1 位と最下位", q2.ranking(scores, "mape"), (MEAN, LGBM))
check("問題2 R2 の 1 位と最下位", q2.ranking(scores, "r2"), (LINEAR, MEAN))
check("問題2 平均予測が 1 位になった指標の数", q2.count_firsts(scores, MEAN), 2)
check("問題2 線形回帰が 1 位になった指標の数", q2.count_firsts(scores, LINEAR), 2)

q3 = importlib.import_module("q3_negative_r2")
check_close("問題3 定義どおりの R2（全部 3.0）", q3.r2_by_hand(y_test, guess), -2.6921)
q3_res, q3_tot = q3.sums_of_squares(y_test, guess)
check("問題3 SSres が SStot より大きいこと", q3_res > q3_tot, True)

q4 = importlib.import_module("q4_residual_diagnosis")
q4_summary = q4.diagnose(y_test, preds[LGBM])
check_close("問題4 残差の平均", q4_summary["mean"], -0.0088)
check_close("問題4 残差の標準偏差", q4_summary["std"], 0.4880)
check_close("問題4 残差の最大絶対値", q4_summary["max_abs"], 1.5971)
check("問題4 大きく外した件数が 1 件以上あること", q4_summary["big_count"] >= 1, True)
q4_star, q4_value = q4.worst_star(grouped)
check_close("問題4 偏りがいちばん大きい星", q4_star, 3.0, tol=1e-9)
check_close("問題4 その星の残差の平均", q4_value, -0.6641)

q5 = importlib.import_module("q5_outlier_sensitivity")
q5_base, q5_swapped = q5.sweep(y_test, preds[LGBM], q5.SWAP_VALUES)
q5_diff = q5.deltas(q5_base, q5_swapped)
check_close("問題5 星 10 に差し替えたときの MAE", q5_swapped[10.0]["mae"], 0.3913)
check_close("問題5 星 10 に差し替えたときの RMSE", q5_swapped[10.0]["rmse"], 0.4967)
check(
    "問題5 どの値でも RMSE の増え方が MAE より大きいこと",
    all(row["rmse"] > row["mae"] for row in q5_diff.values()),
    True,
)
q5_ratios = [q5_diff[value]["ratio"] for value in q5.SWAP_VALUES]
check("問題5 差し替える値を大きくすると比も大きくなること", all(a < b for a, b in zip(q5_ratios, q5_ratios[1:])), True)
q5_slope = (q5_diff[20.0]["mae"] - q5_diff[6.0]["mae"]) / (20.0 - 6.0)
check_close("問題5 MAE の 1 単位あたりの増え方（1/件数）", q5_slope, 1 / len(y_test), tol=1e-12)

q6 = importlib.import_module("q6_metric_choice")
check("問題6 要件の数", len(q6.REQUIREMENTS), 3)
check(
    "問題6 要件ごとに選ぶ指標",
    [metric for _, metric in q6.REQUIREMENTS],
    ["mae", "rmse", "r2"],
)
check("問題6 MAE を要件にすると平均予測が採用されること", best_model(scores, "mae"), MEAN)
check("問題6 RMSE を要件にすると線形回帰が採用されること", best_model(scores, "rmse"), LINEAR)
within = {name: q6.within_tolerance(y_test, pred) for name, pred in preds.items()}
check("問題6 ±0.5 に入った割合が 0〜1 の範囲にあること", all(0.0 <= value <= 1.0 for value in within.values()), True)
check("問題6 実測に 0 を混ぜた MAPE が 1,000,000 を超えること", q6.mape_with_zero(y_test, preds[LGBM]) > 1e6, True)
for star in STARS:
    check(f"問題6 実測 星 {star:.0f} の行が評価データに存在すること", int(grouped.loc[star, "count"]) > 0, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 21 のすべての検証に成功しました。")
