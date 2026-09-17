"""最終プロジェクト（再購入予測）の検証スクリプト。

「最終プロジェクト：再購入予測モデルを作り切る」の本文・要件・解答例に載せた数値と
挙動が、いまこの環境で再現できるかを確認します。期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/final01/verify_final01.py
"""

from __future__ import annotations

import contextlib
import io
import platform
import warnings
from pathlib import Path

import baseline as baseline_script
import build_dataset
import explain
import figures
import joblib
import leak_audit as leak_script
import lightgbm
import models
import monitor
import numpy as np
import pandas as pd
import report
import serve
import sklearn
import thresholds
import validate
from common import (
    CAPACITY,
    DATA_DIR,
    FEATURES,
    LEAK_CHECKLIST,
    NUMERIC,
    OUT_DIR,
    REPORT_PATH,
    baseline,
    capacity_plan,
    cv_scores,
    dataset,
    fitted,
    leak_audit,
    monitoring_plan,
    shap_additivity,
    shap_bundle,
    shap_global,
)

TOLERANCE = 0.005  # 指標の許容誤差（本書共通）
TIGHT = 0.002      # 標準偏差や正例率など、もともと小さい値に使う許容誤差
SIZE_KB = 676.2    # joblib で保存したファイルのサイズ
SIZE_RATIO = 0.10  # ファイルサイズは ±10% まで許す（版によって少し変わる）

EXPECTED_VERSIONS = {
    "python": "3.12.14",
    "pandas": "3.0.5",
    "numpy": "2.5.3",
    "scikit-learn": "1.9.0",
    "lightgbm": "4.7.0",
    "joblib": "1.6.0",
}
ACTUAL_VERSIONS = {
    "python": platform.python_version(),
    "pandas": pd.__version__,
    "numpy": np.__version__,
    "scikit-learn": sklearn.__version__,
    "lightgbm": lightgbm.__version__,
    "joblib": joblib.__version__,
}

# 閾値ごとの成績（適合率 / 再現率 / F1 / 送る / 当たり / 空振り / 見逃し / 当たらなかった負例）
EXPECTED_THRESHOLDS = [
    (0.3, 0.6997, 0.9351, 0.8005, 1442, 1009, 433, 70, 144),
    (0.5, 0.7384, 0.8082, 0.7717, 1181, 872, 309, 207, 268),
    (0.7, 0.8065, 0.6413, 0.7145, 858, 692, 166, 387, 411),
]
EXPECTED_MODELS = {
    "logistic": (0.7729, 0.8679, 0.7101, 0.7694, 0.0104),
    "lgbm": (0.7411, 0.8438, 0.6884, 0.7458, 0.0111),
}
EXPECTED_VALIDATION = [
    "必須の列が足りません",
    "数値で渡してください",
    "の範囲で渡してください",
    "学習時になかった値が入っています",
]
EXPECTED_PLAN_NAMES = ["入力の分布（PSI）", "月次の性能（ROC AUC）", "実際の再購入率", "予測確率の平均", "時間の経過"]

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


missing = [name for name in ("books", "customers", "orders") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 0. ライブラリのバージョン
# ------------------------------------------------------------------
for name, expected in EXPECTED_VERSIONS.items():
    check(f"{name} のバージョン", ACTUAL_VERSIONS[name], expected)

# ------------------------------------------------------------------
# 1. すべてのスクリプトが最後まで動くこと（出力は抑制する）
# ------------------------------------------------------------------
for name in figures.FIGURES:
    (Path(OUT_DIR) / name).unlink(missing_ok=True)

modules = [
    build_dataset,
    baseline_script,
    models,
    validate,
    leak_script,
    thresholds,
    explain,
    serve,
    monitor,
    figures,
    report,
]
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):
        for module in modules:
            module.main()
    glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("スクリプトが最後まで動いた数", len(modules), 11)
check("図の描画で出たフォント欠落の警告の数", len(glyph_warnings), 0)

for name in figures.FIGURES:
    path = Path(OUT_DIR) / name
    size = path.stat().st_size if path.exists() else 0
    print(f"---  {name}: {size:,} バイト")
    check(f"{name} が保存され、サイズが 0 より大きいこと", size > 0, True)
check("図の枚数", len(figures.FIGURES), 4)

# ------------------------------------------------------------------
# 2. 期間の切り方と母集団（課題1）
# ------------------------------------------------------------------
info = build_dataset.summary()
check("cutoff", info["cutoff"], "2026-06-03")
check("予測期間の開始日", info["label_start"], "2026-06-04")
check("基準日", info["as_of"], "2026-09-01")
check("予測する期間の長さ（日）", info["horizon_days"], 90)
check("有効注文の件数", info["n_valid_orders"], 57869)
check("有効注文がある顧客（全期間）", info["all_customers"], 7629)
check("対象顧客の人数", info["n_customers"], 6623)
check("cutoff で切って外れた顧客", info["dropped"], 1006)
check("再購入した顧客の人数", info["n_positive"], 4314)
check("再購入しなかった顧客の人数", info["n_negative"], 2309)
check_close("正例率", info["positive_rate"], 0.6514, tol=TIGHT)
check("特徴量の数", info["n_features"], 11)
check("数値の特徴量の数", info["n_numeric"], 9)
check("カテゴリの特徴量の数", info["n_categorical"], 2)
check("訓練データの件数", info["n_train"], 4967)
check("評価データの件数", info["n_test"], 1656)
check("評価データの正例", info["n_positive_test"], 1079)
check("評価データの負例", info["n_negative_test"], 577)
check_close("評価データの正例率", info["positive_rate_test"], 0.6516, tol=TIGHT)
check("観測期間の注文が cutoff 以内であること", info["past_within_cutoff"], True)
check("数値列に欠損がないこと", info["numeric_has_no_nan"], True)
check("目的変数が 0 と 1 だけであること", info["target_is_binary"], True)
check("特徴量に予測期間の列が入っていないこと", "future_orders" in FEATURES, False)

# ------------------------------------------------------------------
# 3. ベースライン（課題2）
# ------------------------------------------------------------------
base = baseline()
check("多数クラス", base["major"], 1)
check_close("ベースラインの accuracy", base["accuracy"], 0.6516, tol=TIGHT)
check_close("ベースラインの ROC AUC", base["roc_auc"], 0.5000, tol=TIGHT)
check_close("ベースラインの PR-AUC", base["pr_auc"], 0.6516, tol=TIGHT)
check("PR-AUC のベースラインが正例率と一致すること", abs(base["pr_auc"] - base["positive_rate_test"]) < 1e-9, True)

# ------------------------------------------------------------------
# 4. 2 本のモデル（課題3）と交差検証（課題4）
# ------------------------------------------------------------------
comparison = models.compare()
for row in comparison["rows"]:
    roc, pr, accuracy, cv_mean, cv_std = EXPECTED_MODELS[row["kind"]]
    check_close(f"{row['label']}の ROC AUC", row["roc_auc"], roc)
    check_close(f"{row['label']}の PR-AUC", row["pr_auc"], pr)
    check_close(f"{row['label']}の accuracy", row["accuracy"], accuracy)
    check(f"{row['label']}の Pipeline のステップ名", row["steps"], ["pre", "model"])
    check(f"{row['label']}の前処理後の列数", row["n_output_columns"], 20)
    cv = cv_scores(row["kind"])
    check(f"{row['label']}の fold の数", len(cv["scores"]), 5)
    check_close(f"{row['label']}の交差検証の平均", cv["mean"], cv_mean)
    check_close(f"{row['label']}の交差検証の標準偏差", cv["std"], cv_std, tol=TIGHT)

check_close("ロジスティック回帰の accuracy の改善幅", comparison["rows"][0]["accuracy_gain"], 0.0585, tol=TIGHT)
check_close("LightGBM の accuracy の改善幅", comparison["rows"][1]["accuracy_gain"], 0.0368, tol=TIGHT)
check("線形モデルが勝つこと", comparison["simple_wins"], True)
check_close("2 本の ROC AUC の差", comparison["gap"], 0.0318, tol=TIGHT)

crossed = validate.cross_check()
check_close("交差検証の平均の差", crossed["cv_gap"], 0.0236, tol=TIGHT)
check_close("ホールドアウトの差", crossed["holdout_gap"], 0.0318, tol=TIGHT)
check("差が標準偏差より大きいこと", crossed["gap_beats_std"], True)
check("交差検証でも同じモデルが勝つこと", crossed["same_winner"], True)
for row in crossed["rows"]:
    check(f"{row['label']}: ホールドアウトが 2σ に収まること", row["holdout_within_band"], True)
check_close("ロジスティック回帰のホールドアウトと平均の差", crossed["logistic"]["difference"], 0.0035, tol=TIGHT)
check_close("LightGBM のホールドアウトと平均の差", crossed["lgbm"]["difference"], 0.0047, tol=TIGHT)

# ------------------------------------------------------------------
# 5. リークの点検（課題5）
# ------------------------------------------------------------------
audit = leak_audit()
check("リークなしの特徴量の数", audit["n_features_clean"], 11)
check("リークありの特徴量の数", audit["n_features_leaked"], 12)
check_close("リークなしの ROC AUC", audit["clean_roc_auc"], 0.7411)
check_close("リークなしの PR-AUC", audit["clean_pr_auc"], 0.8438)
check_close("リークありの ROC AUC", audit["leaked_roc_auc"], 1.0000)
check_close("リークありの PR-AUC", audit["leaked_pr_auc"], 1.0000)
check_close("跳ね幅", audit["gap"], 0.2589)
check("予測期間の注文が 0 の顧客", audit["zero_rows"], 2309)
check_close("その顧客の再購入率", audit["zero_positive_rate"], 0.0000, tol=TIGHT)
check("その列が目的変数そのものであること", audit["is_target_itself"], True)
check("チェックリストの項目数", len(LEAK_CHECKLIST), 5)
check("チェックリストが解答と一致すること", audit["checklist"], list(LEAK_CHECKLIST))

# ------------------------------------------------------------------
# 6. 閾値と予算（課題6）
# ------------------------------------------------------------------
table = thresholds.table()
check("閾値の行数", len(table), 3)
for row, expected in zip(table.itertuples(), EXPECTED_THRESHOLDS):
    threshold, precision, recall, f1, n_sent, tp, fp, fn, tn = expected
    check_close(f"閾値 {threshold} の適合率", row.precision, precision)
    check_close(f"閾値 {threshold} の再現率", row.recall, recall)
    check_close(f"閾値 {threshold} の F1", row.f1, f1)
    check(f"閾値 {threshold} の送る人数", int(row.n_sent), n_sent)
    check(f"閾値 {threshold} の当たり", int(row.tp), tp)
    check(f"閾値 {threshold} の空振り", int(row.fp), fp)
    check(f"閾値 {threshold} の見逃し", int(row.fn), fn)
    check(f"閾値 {threshold} の当たらなかった負例", int(row.tn), tn)
    check(f"閾値 {threshold} の 4 象限の合計が評価データと一致", int(row.tp + row.fp + row.fn + row.tn), 1656)

plan = capacity_plan(table)
check("送れる上限（通）", plan["capacity"], 1000)
check("送れる上限が予算 ÷ 単価と一致すること", CAPACITY, 500_000 // 500)
check_close("選んだ閾値", plan["threshold"], 0.7, tol=1e-9)
check_close("選んだ閾値の適合率", plan["precision"], 0.8065)
check_close("選んだ閾値の再現率", plan["recall"], 0.6413)
check("選んだ閾値で送る人数", plan["n_sent"], 858)
check("当たり", plan["tp"], 692)
check("空振り", plan["fp"], 166)
check("見逃し", plan["fn"], 387)
check("費用（円）", plan["cost_yen"], 429_000)
check("予算の残り（円）", plan["left_yen"], 71_000)
check("枠の余り（通）", plan["spare"], 142)
check_close("F1 が最大の閾値", plan["best_f1_threshold"], 0.3, tol=1e-9)
check_close("その F1", plan["best_f1"], 0.8005)
check("その閾値で送る人数", plan["best_f1_n_sent"], 1442)
check("あふれる通数", plan["best_f1_over"], 442)
check("同じ枠を無作為に配った当たり", plan["random_hits"], 652)
check("モデルのほうが当たりが多いこと", plan["beats_random"], True)

# ------------------------------------------------------------------
# 7. SHAP による説明（課題7）
# ------------------------------------------------------------------
bundle = shap_bundle()
check("前処理後の行列の形", bundle["matrix"].shape, (1656, 20))
check("shap_values の形", bundle["values"].shape, (1656, 20))
check("列名の数", len(bundle["names"]), 20)
check("expected_value の dtype", bundle["base_dtype"], "float64")
check("expected_value がスカラーであること", bundle["base_shape"], ())
check("TreeExplainer の警告が 1 件以上捕まえられていること", len(bundle["warnings"]) >= 1, True)
check("SHAP の平均絶対値の行数", len(shap_global()), 20)

additivity = shap_additivity()
check("加法性が成り立つこと", additivity["matches"], True)
check_close("分解から復元した確率", additivity["proba_from_shap"], 0.4067)
check_close("モデルが直接返す確率", additivity["proba_from_model"], 0.4067)
check("説明文に確率が入っていること", "0.4067" in explain.sentence(), True)
check("局所的説明の行数", len(explain.shap_local()), 20)

# ------------------------------------------------------------------
# 8. 保存と 1 件推論（課題8）
# ------------------------------------------------------------------
served = serve.analyze()
check_close("保存したファイルのサイズ（KB）", served["kb"], SIZE_KB, tol=SIZE_KB * SIZE_RATIO)
check("保存した Pipeline のステップ名", served["steps"], ["pre", "model"])
check("読み込んだ Pipeline のステップ名", served["restored_steps"], ["pre", "model"])
check("メタデータの項目数", len(served["meta_keys"]), 18)
check("記録したバージョンの項目数", served["n_versions"], 6)
check("バージョンの食い違い", served["n_differences"], 0)
check("読み込んだモデルの予測が一致すること（np.allclose）", served["allclose"], True)
check("予測の最大の差が 0 であること", served["max_difference"] <= 1e-12, True)
check_close("1 件推論の再購入確率", served["proba"], 0.4067)
check("その確率での判断", served["decision"], "送らない")
check("検証後の列の数", served["n_clean_columns"], 11)
check("region の欠損は受け付けること", served["region_missing_ok"], True)
check("壊れた入力の数", len(served["messages"]), 4)
for index, keyword in enumerate(EXPECTED_VALIDATION):
    message = served["messages"][index]
    check(f"検証 {index + 1} が ValueError であること", message.startswith("ValueError"), True)
    check(f"検証 {index + 1} の文面に「{keyword}」が含まれること", keyword in message, True)

# ------------------------------------------------------------------
# 9. 監視の計画（課題9）
# ------------------------------------------------------------------
rules = monitoring_plan()
check("監視する項目の数", len(rules), 5)
check("監視する項目の名前", [str(rule["name"]) for rule in rules], EXPECTED_PLAN_NAMES)
probe = monitor.probe()
check("PSI を測った倍率の数", len(probe["values"]), 3)
check("同じ分布どうしの PSI が 0 であること", probe["self_psi"] == 0.0, True)
check("×1.0 の判定が「安定」であること", probe["stable_at_one"], True)
check("ずらすほど PSI が大きくなること", probe["monotonic"], True)
check("×3.0 では「安定」でなくなること", probe["not_stable_at_last"], True)

# ------------------------------------------------------------------
# 10. 報告カードとレポート（課題11）
# ------------------------------------------------------------------
gathered = report.gather()
check("報告カードの行数", len(report.card(gathered)), 12)
for label, ok in report.checks(gathered):
    check(f"検算: {label}", ok, True)
text = report.build_report(gathered)
check("レポートが書き出されていること", REPORT_PATH.exists(), True)
check("レポートの見出しの数", text.count("\n## "), 8)
check("レポートに採用した閾値が書かれていること", "採用する閾値は 0.7" in text, True)
check("レポートにベースラインが書かれていること", "0.6516" in text, True)
check("レポートにリークの数値が書かれていること", "1.0000" in text, True)
check("レポートに 4 枚の図が書かれていること", all(name in text for name in figures.FIGURES), True)
check("レポートに「言えないこと」の節があること", "言えないこと" in text, True)

# ------------------------------------------------------------------
# 11. 母集団と特徴量の最終確認（本文の数値と表の整合）
# ------------------------------------------------------------------
data = dataset()
check("特徴量の列の順番が本文と一致すること", list(data["X"].columns), FEATURES)
check("数値の特徴量の名前（先頭 3 列）", NUMERIC[:3], ["n_orders", "total_amount", "mean_amount"])
check_close("採用モデルの ROC AUC（再確認）", fitted("lgbm")["roc_auc"], 0.7411)
check_close("参考モデルの ROC AUC（再確認）", fitted("logistic")["roc_auc"], 0.7729)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("最終プロジェクトのすべての検証に成功しました。")
