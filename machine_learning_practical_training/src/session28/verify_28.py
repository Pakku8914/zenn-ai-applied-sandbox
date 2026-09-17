"""セッション 28 の検証スクリプト。

「セッション28：モデルの保存・推論・監視」の本文・練習問題・解答に載せた数値と挙動が、
いまこの環境で再現できるかを確認します。期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session28/verify_28.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import drift_injected
import drift_psi
import performance_decay
import predict_one as single_prediction  # 関数 predict_one と名前が衝突しないように別名で読む
import q1_save_load
import q2_version_meta
import q3_validate_input
import q4_psi_table
import q5_inject_drift
import q6_retrain_decision
import retrain_policy
import save_and_load
import version_guard
from common import (
    CUTOFF,
    DATA_DIR,
    FEATURES,
    LABEL_START,
    MODEL_PATH,
    NUMERIC,
    OLD_MODEL_PATH,
    OUT_DIR,
    allowed_levels,
    build_meta,
    cancel_rates,
    cancel_time_split,
    compare_versions,
    ensure_model,
    monthly_auc,
    predict_one,
    psi_table,
    quantity_drift,
    repeat_bundle,
    retrain_rules,
    sample_record,
    should_retrain,
    trend_summary,
    unit_price_drift,
    validate_record,
)

TOLERANCE = 0.005   # 指標の許容誤差（本書共通）
TIGHT = 0.001       # 標準偏差・傾きなど、もともと小さい値に使う許容誤差
PSI_TOL = 0.002     # PSI の許容誤差
MEAN_TOL = 0.05     # 単価の平均（円）の許容誤差
SIZE_KB = 676.2     # joblib で保存したファイルのサイズ
SIZE_RATIO = 0.10   # ファイルサイズは ±10% まで許す（版によって少し変わる）

EXPECTED_VERSIONS = {
    "python": "3.12.14",
    "pandas": "3.0.5",
    "numpy": "2.5.3",
    "scikit-learn": "1.9.0",
    "lightgbm": "4.7.0",
    "joblib": "1.6.0",
}
EXPECTED_PSI = {
    "unit_price": 0.0010,
    "quantity": 0.0000,
    "discount_rate": 0.0001,
    "amount": 0.0027,
}
EXPECTED_DRIFT = [(1.00, 0.0010, "安定"), (1.05, 0.0192, "安定"), (1.20, 0.2541, "要再学習"), (1.50, 0.9056, "要再学習")]
EXPECTED_MONTHLY = [
    ("2026-04", 0.7586),
    ("2026-05", 0.7259),
    ("2026-06", 0.7525),
    ("2026-07", 0.7407),
    ("2026-08", 0.7790),
    ("2026-09", 0.7661),
]
EXPECTED_VALIDATION = [
    "入力は dict で渡してください",
    "必須の列が足りません",
    "欠損を受け付けません",
    "数値で渡してください",
    "の範囲で渡してください",
    "学習時になかった値が入っています",
]
FIGURES = ["s28_psi.png", "s28_drift_shift.png", "s28_monthly_auc.png", "s28_q5_drift.png"]

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
# 0. 本文と練習問題のスクリプトが最後まで動くこと（出力は抑制する）
# ------------------------------------------------------------------
for name in FIGURES:
    (Path(OUT_DIR) / name).unlink(missing_ok=True)

modules = [
    # 本文のスクリプト
    save_and_load,
    version_guard,
    single_prediction,
    drift_psi,
    drift_injected,
    performance_decay,
    retrain_policy,
    # 練習問題の解答
    q1_save_load,
    q2_version_meta,
    q3_validate_input,
    q4_psi_table,
    q5_inject_drift,
    q6_retrain_decision,
]
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):
        for module in modules:
            module.main()
    glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("スクリプトが最後まで動いた数", len(modules), 13)
check("図の描画で出たフォント欠落の警告の数", len(glyph_warnings), 0)

for name in FIGURES:
    path = Path(OUT_DIR) / name
    size = path.stat().st_size if path.exists() else 0
    print(f"---  {name}: {size:,} バイト")
    check(f"{name} が保存され、サイズが 0 より大きいこと", size > 0, True)

# ------------------------------------------------------------------
# 1. 再購入予測の母集団（保存と推論の題材）
# ------------------------------------------------------------------
bundle = repeat_bundle()
check("cutoff", str(CUTOFF.date()), "2026-06-03")
check("目的変数を数える期間の開始日", str(LABEL_START.date()), "2026-06-04")
check("対象顧客の人数", int(len(bundle["df"])), 6623)
check("再購入した顧客の人数", int(bundle["y"].sum()), 4314)
check_close("正例率", float(bundle["y"].mean()), 0.6514, tol=TIGHT)
check("訓練データの件数", int(len(bundle["X_train"])), 4967)
check("評価データの件数", int(len(bundle["X_test"])), 1656)
check("特徴量の数", len(FEATURES), 11)
check("数値列に欠損がないこと", int(bundle["X"][NUMERIC].isna().sum().sum()), 0)
check_close("参考: ROC AUC（性能の議論はこの章では行わない）", bundle["roc_auc"], 0.7411)
check_close("参考: PR-AUC", bundle["pr_auc"], 0.8438)

# ------------------------------------------------------------------
# 2. 保存と読み込み（本文 1〜2 節）
# ------------------------------------------------------------------
saved = save_and_load.save()
check_close("保存したファイルのサイズ（KB）", saved["kb"], SIZE_KB, tol=SIZE_KB * SIZE_RATIO)
check("Pipeline のステップ名", saved["steps"], ["pre", "model"])
restored = save_and_load.reload()
check("読み込んだ Pipeline のステップ名", restored["steps"], ["pre", "model"])
check("読み込んだモデルの予測が一致すること（np.allclose）", restored["allclose"], True)
check("予測の最大の差が 0 であること", restored["max_difference"] <= 1e-12, True)
check("読み込み時のバージョンの食い違い", restored["n_version_differences"], 0)
check("メタデータのキーの数", len(restored["meta_keys"]), 14)

# ------------------------------------------------------------------
# 3. バージョンの結びつき（本文 3 節）
# ------------------------------------------------------------------
meta = build_meta(bundle)
check("記録したバージョンの項目数", len(meta["versions"]), 6)
for name, expected in EXPECTED_VERSIONS.items():
    check(f"メタデータの {name}", meta["versions"][name], expected)
check("いまのバージョンと保存時の記録が一致すること", all(row["same"] for row in compare_versions(meta)), True)
check("メタデータの cutoff", meta["cutoff"], "2026-06-03")
check("メタデータの horizon_days", meta["horizon_days"], 90)
check("メタデータの nullable", meta["nullable"], ["region"])

guard = version_guard.guard_demo(meta)
check("記録を書き換えると照合で落ちること", guard["strict_message"].startswith("ValueError"), True)
check("書き換えた項目の数", guard["n_differences"], 2)
check(
    "食い違いの中身",
    [(row["name"], row["saved"], row["current"]) for row in guard["differences"]],
    [("scikit-learn", "1.6.1", "1.9.0"), ("lightgbm", "4.5.0", "4.7.0")],
)
check("strict=False なら読み込めること", OLD_MODEL_PATH.exists(), True)

# ------------------------------------------------------------------
# 4. 1 件推論と入力の検証（本文 4 節）
# ------------------------------------------------------------------
model, loaded_meta, differences = ensure_model(MODEL_PATH)
record = sample_record()
check("1 件推論に使う行の n_orders", int(record["n_orders"]), 7)
check("1 件推論に使う行の recency", int(record["recency"]), 241)
check_close("1 件推論に使う行の total_amount", float(record["total_amount"]), 11550.5, tol=0.05)
check_close("1 件推論の再購入確率", predict_one(model, record), 0.4067)
clean = validate_record(record)
check("検証後の列の数", len(clean), 11)
check("検証後の列の順番が学習時と同じこと", list(clean) == FEATURES, True)
check("channel の水準の数", len(allowed_levels()["channel"]), 4)
check("channel の水準", list(allowed_levels()["channel"]), ["SNS", "メルマガ", "検索", "紹介"])
check("region の水準の数", len(allowed_levels()["region"]), 7)
check(
    "region の水準",
    list(allowed_levels()["region"]),
    ["北海道", "大阪", "宮城", "広島", "愛知", "東京", "福岡"],
)

q3 = q3_validate_input.analyze()
check("問題3 の落ちた件数", q3["n_failed"], 6)
for index, keyword in enumerate(EXPECTED_VALIDATION):
    message = q3["messages"][index]["message"]
    check(f"検証 {index + 1} の文面に「{keyword}」が含まれること", keyword in message, True)
    check(f"検証 {index + 1} が ValueError であること", message.startswith("ValueError"), True)
check("region の欠損は受け付けること", q3["region_missing_ok"], True)
check("channel の欠損は落とすこと", q3["channel_message"].startswith("ValueError"), True)
check_close("問題3 の再購入確率", q3["proba"], 0.4067)

# ------------------------------------------------------------------
# 5. データドリフト（本文 5 節）— このデータにはドリフトが無い
# ------------------------------------------------------------------
rates = cancel_rates()
check("前半の注文件数", rates["before_n"], 15657)
check("後半の注文件数", rates["after_n"], 44374)
check("前半 + 後半が 60,031 件になること", rates["before_n"] + rates["after_n"], 60031)
check("前半の有効注文", rates["before_valid"], 15115)
check("後半の有効注文", rates["after_valid"], 42754)
check("有効注文の合計が 57,869 件になること", rates["before_valid"] + rates["after_valid"], 57869)
check_close("前半のキャンセル率", rates["before_rate"], 0.0346, tol=TIGHT)
check_close("後半のキャンセル率", rates["after_rate"], 0.0365, tol=TIGHT)

drift = psi_table()
check("PSI を測った列の数", len(drift), 4)
for row in drift.itertuples():
    check_close(f"PSI（{row.column}）", row.psi, EXPECTED_PSI[str(row.column)], tol=PSI_TOL)
    check(f"判定（{row.column}）", row.judgement, "安定")
check("いちばん大きい PSI の列", str(drift.loc[drift["psi"].idxmax(), "column"]), "amount")
price = drift.loc[drift["column"] == "unit_price"].iloc[0]
check_close("前半の単価の平均", float(price["before_mean"]), 1845.51, tol=MEAN_TOL)
check_close("後半の単価の平均", float(price["after_mean"]), 1842.71, tol=MEAN_TOL)

# ------------------------------------------------------------------
# 6. 人工的なドリフト（本文 6 節）— 監視が動くことを確かめる
# ------------------------------------------------------------------
injected = unit_price_drift()
check("試した倍率の数", len(injected), 4)
for row, (ratio, expected_psi, expected_verdict) in zip(injected.itertuples(), EXPECTED_DRIFT):
    check_close(f"単価 ×{ratio:.2f} の PSI", row.psi, expected_psi, tol=PSI_TOL)
    check(f"単価 ×{ratio:.2f} の判定", row.judgement, expected_verdict)
check("PSI が単調に増えること", list(injected["psi"]) == sorted(injected["psi"]), True)

quantity = quantity_drift()
check("差し替えた件数", quantity["n_changed"], 12826)
check_close("差し替え前の数量の PSI", quantity["psi_plain"], 0.0000, tol=PSI_TOL)
check_close("差し替え後の数量の PSI", quantity["psi_injected"], 0.3059, tol=PSI_TOL)
check("差し替え後の判定", quantity["judgement_injected"], "要再学習")

q5 = q5_inject_drift.analyze()
check_close("問題5 のはじめて注意を超える倍率", q5["first_fired_ratio"], 1.20, tol=1e-9)
check("問題5 の「安定」でなくなった倍率の数", q5["n_not_stable"], 2)

# ------------------------------------------------------------------
# 7. 性能の劣化（本文 7 節）
# ------------------------------------------------------------------
split = cancel_time_split()
check("時間分割の学習件数", split["n_train"], 15657)
check("時間分割の評価件数", split["n_test"], 44374)
check("学習データの最終日", str(split["train_end"].date()), "2025-08-31")
check_close("時間分割の ROC AUC", split["roc_auc"], 0.7546)
check_close("時間分割の PR-AUC", split["pr_auc"], 0.1356)
check("無作為分割（0.7911）より低いこと", split["roc_auc"] < 0.7911, True)

table = monthly_auc()
check("月次の行数", len(table), 6)
for row, (month, expected_auc) in zip(table.itertuples(), EXPECTED_MONTHLY):
    check(f"月次の月（{month}）", row.month, month)
    check_close(f"月次 ROC AUC（{month}）", row.roc_auc, expected_auc)

trend = trend_summary(table)
check_close("月次 AUC の平均", trend["mean"], 0.7538)
check_close("月次 AUC の標準偏差", trend["std"], 0.0171, tol=TIGHT)
check_close("ばらつきの下限（平均 − 2σ）", trend["lower"], 0.7195)
check_close("ばらつきの上限（平均 + 2σ）", trend["upper"], 0.7881)
check_close("月次 AUC の最小", trend["min"], 0.7259)
check_close("月次 AUC の最大", trend["max"], 0.7790)
check_close("月次 AUC の幅", trend["span"], 0.0531, tol=TIGHT)
check_close("1 か月あたりの傾き", trend["slope"], 0.0053, tol=TIGHT)
check("下限を下回った月の数", trend["n_below"], 0)
check("2 か月連続で下回っていないこと", trend["consecutive_below"], False)
check("下降トレンドと判定されないこと", trend["declining"], False)

# ------------------------------------------------------------------
# 8. 再学習の判断（本文 8 節）
# ------------------------------------------------------------------
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
# 9. 練習問題の解答（残り）
# ------------------------------------------------------------------
q1 = q1_save_load.analyze()
check_close("問題1 のファイルサイズ（KB）", q1["kb"], SIZE_KB, tol=SIZE_KB * SIZE_RATIO)
check("問題1 の np.allclose", q1["allclose"], True)
check("問題1 の最大の差が 0 であること", q1["max_difference"] <= 1e-12, True)
check("問題1 のクラスの一致件数", q1["same_class"], 1656)
check("問題1 の中身の型", q1["payload_type"], "tuple")
check("問題1 の中身の要素数", q1["payload_size"], 2)
check("問題1 の 1 つ目の型", q1["model_type"], "Pipeline")
check("問題1 の 2 つ目の型", q1["meta_type"], "dict")

q2 = q2_version_meta.analyze()
check("問題2 のメタデータのキーの数", len(q2["meta_keys"]), 14)
check("問題2 の照合の食い違い", q2["n_differences"], 0)
check("問題2 の書き換え後の食い違い", q2["n_old_differences"], 1)
check("問題2 の書き換えた項目", q2["old_differences"][0]["name"], "scikit-learn")
check("問題2 の strict=True が落ちること", q2["strict_message"].startswith("ValueError"), True)

q4 = q4_psi_table.analyze()
check("問題4 の自作 PSI が common と一致すること", q4["matches"], True)
check_close("問題4 の最大の PSI", q4["worst_psi"], 0.0027, tol=PSI_TOL)
check("問題4 の最大の列", q4["worst_column"], "amount")
check("問題4 の安定な列の数", q4["n_stable"], 4)

q6 = q6_retrain_decision.analyze()
check_close("問題6 の ROC AUC の差", q6["roc_gap"], -0.0365)
check_close("問題6 の PR-AUC の差", q6["pr_gap"], -0.0471)
check("問題6 の再学習の判定", q6["decision"]["retrain"], True)
check("問題6 の発火した条件の数", q6["decision"]["n_fired"], 2)
check("問題6 の下降トレンドの判定", q6["trend"]["declining"], False)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 28 のすべての検証に成功しました。")
