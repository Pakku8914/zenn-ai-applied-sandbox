"""セッション 22 の検証スクリプト。

「セッション22：交差検証とデータリーク ― 性能の見積もりが壊れる仕組み」の本文・
練習問題・解答に載せた数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session22/verify_22.py
"""

from __future__ import annotations

import warnings
from pathlib import Path

from body_length_leak import compare as compare_body_length
from common import DATA_DIR, OUT_DIR, load_review_table
from holdout_vs_cv import compare as compare_holdout
from leak_checklist import CHECKLIST, audit as audit_table, findings
from noise_selection_leak import (
    FIGURE_NAME as NOISE_FIGURE,
    experiment as noise_experiment,
    make_figure as make_noise_figure,
)
from q1_cv_vs_holdout import analyze as analyze_q1
from q2_stratify_rates import analyze as analyze_q2
from q3_group_split import analyze as analyze_q3
from q4_scaler_leak_sizes import analyze as analyze_q4
from q5_timeseries_cv import analyze as analyze_q5
from q6_noise_leak import analyze as analyze_q6
from q7_leak_audit import CHECKS, audit as audit_spec, build_specs
from scaler_leak import gap as scaler_gap
from split_strategies import (
    FIGURE_NAME as FOLD_FIGURE,
    group_facts,
    make_figure as make_fold_figure,
    strategies,
)

TOLERANCE = 0.005   # 指標の許容誤差（本書共通）
TIGHT = 0.0005      # 標準偏差や「差」など、もともと小さい値に使う許容誤差

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


missing = [name for name in ("books", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

df = load_review_table()

# ------------------------------------------------------------------
# 1. 母集団（src/verify_setup.py の 5 節と同じ表であること）
# ------------------------------------------------------------------
check("高評価分類に使うレビュー件数", len(df), 14169)
check_close("高評価（星 4 以上）の割合", float(df["is_high"].mean()), 0.8167, tol=TIGHT)

# ------------------------------------------------------------------
# 2. 1 回のホールドアウトと層化 5 分割交差検証（本文 1 節・問題1）
# ------------------------------------------------------------------
holdout_result = compare_holdout(df)
STRATIFIED_FOLDS = [0.8200, 0.8380, 0.8128, 0.8270, 0.8222]
for number, expected in enumerate(STRATIFIED_FOLDS, start=1):
    check_close(f"層化 5 分割の fold {number} の ROC AUC", holdout_result["scores"][number - 1], expected)
check_close("層化 5 分割の平均", holdout_result["mean"], 0.8240)
check_close("層化 5 分割の標準偏差", holdout_result["std"], 0.0084, tol=TIGHT)
check_close("ホールドアウト 1 回の ROC AUC", holdout_result["holdout"], 0.8265)
check_close("ホールドアウト − 交差検証の平均", holdout_result["gap"], 0.0025, tol=0.001)
check("ホールドアウトが fold の最小〜最大に入ること", holdout_result["inside_range"], True)

q1 = analyze_q1(df)
check("手書きループが cross_val_score と一致すること（問題1）", q1["same_as_manual"], True)
check_close("問題1 の平均", q1["mean"], 0.8240)
check_close("問題1 のホールドアウト", q1["holdout"], 0.8265)

# ------------------------------------------------------------------
# 3. 4 種類の分割（本文 2 節・問題2・問題3・問題5）
# ------------------------------------------------------------------
stratified_row, plain_row, group_row, series_row = strategies(df)
check_close("① 層化 5 分割の平均（4 種比較）", stratified_row["mean"], 0.8240)
check_close("② 層化なし 5 分割の平均", plain_row["mean"], 0.8242)
check_close("② 層化なし 5 分割の標準偏差", plain_row["std"], 0.0113, tol=TIGHT)
check("② の標準偏差が ① より大きいこと", plain_row["std"] > stratified_row["std"], True)
check_close("③ 顧客単位のグループ分割の平均", group_row["mean"], 0.8238)
check_close("③ 顧客単位のグループ分割の標準偏差", group_row["std"], 0.0043, tol=TIGHT)
TIME_SERIES_FOLDS = [0.8354, 0.8203, 0.8300, 0.8272, 0.8189]
for number, expected in enumerate(TIME_SERIES_FOLDS, start=1):
    check_close(f"④ 時系列分割の fold {number} の ROC AUC", series_row["scores"][number - 1], expected)
check_close("④ 時系列分割の平均", series_row["mean"], 0.8264)

facts = group_facts(df)
check("顧客の人数", facts["customers"], 5807)
check("1 顧客あたりの最大レビュー数", facts["max_per_customer"], 15)

q2 = analyze_q2(df)
PLAIN_RATES = [0.8155, 0.8183, 0.8250, 0.8059, 0.8189]
for number, expected in enumerate(PLAIN_RATES, start=1):
    check_close(f"層化なし fold {number} の正例率", q2["plain_rates"][number - 1], expected, tol=TIGHT)
check("層化ありの正例率が全体から 0.001 以内にそろうこと", q2["strat_worst_diff"] < 0.001, True)
check("層化なしのほうがスコアの標準偏差が大きいこと", q2["plain_std_is_larger"], True)
check("層化あり・なしで平均はほとんど変わらないこと", q2["mean_gap"] < TOLERANCE, True)

q3 = analyze_q3(df)
check("問題3 の顧客の人数", q3["customers"], 5807)
check("問題3 のレビュー件数", q3["reviews"], 14169)
check("問題3 の 1 顧客あたり最大レビュー数", q3["max_per_customer"], 15)
check("グループ分割では fold をまたぐ顧客が 1 人もいないこと", q3["group_is_clean"], True)
check("層化分割では fold をまたぐ顧客がいること", q3["strat_has_overlap"], True)
check_close("問題3 のグループ分割の平均", q3["group_mean"], 0.8238)
check("グループ分割と層化分割の差が許容誤差より小さいこと", q3["gap_is_small"], True)

q5 = analyze_q5(df)
EXPECTED_TRAIN_SIZES = [2364, 4725, 7086, 9447, 11808]
for row, n_train in zip(q5["rows"], EXPECTED_TRAIN_SIZES):
    check(f"時系列分割 fold {row['fold']} の訓練件数", row["n_train"], n_train)
    check(f"時系列分割 fold {row['fold']} の評価件数", row["n_test"], 2361)
check("どの fold も訓練データが評価データより前の期間であること", q5["all_in_order"], True)
check("訓練データが fold ごとに増えること", q5["train_grows"], True)
check("一度も評価に使われない先頭の行数", q5["never_evaluated"], 2364)
check("先頭の行数と評価件数の合計が全件数と一致すること", q5["covers_all"], True)
check_close("問題5 の時系列分割の平均", q5["mean"], 0.8264)

# ------------------------------------------------------------------
# 4. 前処理を分割前に当てても数値が動かないこと（本文 4 節・問題4）
# ------------------------------------------------------------------
scaler_full = scaler_gap(df)
check_close("正しい手順（分割 → 訓練データだけで fit）", scaler_full["correct"], 0.8265)
check_close("分割前に全データで fit した場合", scaler_full["leaked"], 0.8265)
check_close("その差（持ち上がらないこと）", scaler_full["gap"], 0.0000, tol=TIGHT)

q4 = analyze_q4(df)
EXPECTED_GAPS = [(100, 0.0000), (200, 0.0023), (500, -0.0004), (2000, 0.0003)]
for row, (size, expected) in zip(q4["rows"], EXPECTED_GAPS):
    check("標本サイズ", int(row["n"]), size)
    check_close(f"n={size} のときのリークによる差", row["gap"], expected)
    check(f"n={size} の差が許容誤差より小さいこと", abs(row["gap"]) < TOLERANCE, True)
check("どの標本サイズでも差が許容誤差より小さいこと", q4["all_within_tolerance"], True)
check("手書きで書いたリーク版でも同じ値になること", q4["by_hand_matches"], True)

# ------------------------------------------------------------------
# 5. 雑音 500 列でも選び方を間違えると当たって見える（本文 5 節・問題6）
# ------------------------------------------------------------------
noise_result = noise_experiment(df)
check("ノイズ列の形", noise_result["shape"], (14169, 500))
check_close("分割前に全データで 10 列を選んだ ROC AUC", noise_result["leaked_auc"], 0.5591)
check_close("訓練データだけで 10 列を選んだ ROC AUC", noise_result["honest_auc"], 0.5086)
check_close("選び方だけで生まれた差", noise_result["gap"], 0.0505)

q6 = analyze_q6(df)
check("問題6 のノイズ列の形", q6["shape"], (14169, 500))
check_close("問題6 のリークあり ROC AUC", q6["leaked"], 0.5591)
check_close("問題6 のリークなし ROC AUC", q6["honest"], 0.5086)
check("リークあり版が当て推量を 0.05 以上上回ること", q6["leaked_beats_chance"], True)
check("正しい手順が当て推量から 0.01 以内であること", q6["honest_is_chance"], True)
check("交差検証でも当て推量とほぼ同じであること", q6["cv_is_chance"], True)

# ------------------------------------------------------------------
# 6. body_length は「結果」である（本文 6 節・問題7）
# ------------------------------------------------------------------
body_length = compare_body_length(df)
check_close("body_length と rating の相関", body_length["corr"], -0.2867)
check_close("body_length を含む 5 特徴量の ROC AUC", body_length["with_length"], 0.8265)
check_close("body_length を外した 4 特徴量の ROC AUC", body_length["without_length"], 0.7763)
check_close("外したときに下がる幅", body_length["gap"], -0.0502)
check("外しても当て推量を上回ること", body_length["without_length"] > 0.5, True)

# ------------------------------------------------------------------
# 7. リーク点検チェックリスト（本文 7 節・問題7）
# ------------------------------------------------------------------
table_facts = audit_table(df)
check("チェックリストの問いの数", len(CHECKLIST), 7)
check("チェックリストに並べた判定の数", len(findings(table_facts)), 7)
check("チェックリストが見つけた「結果」の列", table_facts["result_columns"], ["body_length"])
check("チェックリストが数えた顧客の人数", table_facts["customers"], 5807)
check("同じ顧客が 2 件以上書いていること", table_facts["customer_appears_twice"], True)

specs = build_specs(df)
check("問題7 で監査する実験の数", len(specs), 3)
check_close("実験 A（body_length あり）の ROC AUC", specs[0].model_auc, 0.8265)
check_close("実験 B（body_length なし）の ROC AUC", specs[1].model_auc, 0.7763)
check("問題7 のチェック項目の数", len(CHECKS), 7)
risky_counts = [sum(1 for row in audit_spec(spec) if row["risky"]) for spec in specs]
check("要確認の件数（A・B・C）", risky_counts, [3, 2, 5])
risky_labels_b = [row["label"] for row in audit_spec(specs[1]) if row["risky"]]
check(
    "B で残る要確認は重複と時間の 2 件であること",
    risky_labels_b,
    ["Q3 同じ人・同じ商品の重複", "Q6 時間をまたぐ分割"],
)

# ------------------------------------------------------------------
# 8. 図が保存され、日本語が豆腐（□）にならないこと
# ------------------------------------------------------------------
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    make_fold_figure([stratified_row, plain_row, group_row, series_row])
    make_noise_figure(noise_result)
    glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("日本語フォントの欠落警告の数", len(glyph_warnings), 0)
for name in (FOLD_FIGURE, NOISE_FIGURE):
    path = OUT_DIR / name
    check(f"{name} が保存されていること", path.exists(), True)
    check(f"{name} のファイルサイズが 0 より大きいこと", path.stat().st_size > 0, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 22 のすべての検証に成功しました。")
