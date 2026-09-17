"""中間プロジェクト②の検証スクリプト。

「中間プロジェクト②：キャンセルされる注文を予測する」「同：要件と仕様」「同：解答例」に
載せた数値・図・レポートが、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/mid02/verify_mid02.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import explore
import features
import figures
import leak_audit
import model
import report
import sampling
import thresholds
import validate
from common import DATA_DIR, MONTHLY_CAPACITY, OUT_DIR, format_calls

TOLERANCE = 0.005        # 指標の許容誤差（本書共通）
BRIER_TOLERANCE = 0.001  # Brier スコアは値が小さいので細かく見る

# 母集団と分割（src/verify_setup.py の 6 節・セッション24 と同じ）
EXPECTED_COUNTS = {
    "n_rows": 60031,
    "n_positive": 2162,
    "n_train": 45023,
    "n_test": 15008,
    "n_train_positive": 1621,
    "n_train_negative": 43402,
    "n_test_positive": 541,
}
EXPECTED_RATES = {"rate_all": 0.0360, "rate_train": 0.0360, "rate_test": 0.0360}
# 閾値 0.5 の混同行列 [[TN, FP], [FN, TP]] = [[14438, 29], [512, 29]]
EXPECTED_CONFUSION = {"tn": 14438, "fp": 29, "fn": 512, "tp": 29}
# (閾値, 適合率, 再現率, F1, 陽性と予測, 捕まえた, 見逃した, 1 件あたりの連絡, 表示)
EXPECTED_THRESHOLDS = [
    (0.1, 0.1612, 0.3993, 0.2297, 1340, 216, 325, 6.20, "6.2 件"),
    (0.2, 0.2489, 0.2089, 0.2271, 454, 113, 428, 4.02, "4.0 件"),
    (0.3, 0.3545, 0.1442, 0.2050, 220, 78, 463, 2.82, "2.8 件"),
    (0.5, 0.5000, 0.0536, 0.0968, 58, 29, 512, 2.00, "2.0 件"),
]
EXPECTED_SCORES = {
    "plain": {"roc_auc": 0.7911, "pr_auc": 0.1827, "accuracy": 0.9640, "mean_proba": 0.0352},
    "balanced": {"roc_auc": 0.7901, "pr_auc": 0.1812, "precision": 0.1204, "recall": 0.5841, "mean_proba": 0.2656},
    "under": {"roc_auc": 0.7857, "pr_auc": 0.1563, "mean_proba": 0.3570},
}
EXPECTED_BRIER = {"plain": 0.03235, "balanced": 0.12445, "under": 0.19322}
EXPECTED_UNDER_COUNTS = {
    "n_before": 45023,
    "n_before_positive": 1621,
    "n_before_negative": 43402,
    "n_after": 3242,
    "n_after_positive": 1621,
    "n_after_negative": 1621,
    "n_dropped": 41781,
    "n_test": 15008,
}
# 増分実験（セッション14 の①〜⑦。⑦だけがリーク）
EXPECTED_STEPS = [
    ("①", 3, 0.7391, 0.1133),
    ("②", 5, 0.7911, 0.1827),
    ("③", 7, 0.7886, 0.1769),
    ("④", 10, 0.7878, 0.1793),
    ("⑤", 12, 0.7895, 0.1747),
    ("⑥", 14, 0.7875, 0.1758),
    ("⑦", 15, 0.9664, 0.4969),
]
# 特徴量を足す候補を決めた根拠（セッション14 の再掲）
EXPECTED_CHANNEL_RATES = [("SNS", "6.94%"), ("紹介", "2.49%"), ("メルマガ", "2.40%"), ("検索", "2.25%")]
REPORT_HEADINGS = [
    "## 0. 予測タスクと母集団",
    "## 1. 報告する指標",
    "## 2. 運用する閾値とその根拠",
    "## 3. 特徴量の増分実験",
    "## 4. 交差検証とリークの点検",
    "## 5. この予測で言えないこと",
    "## 6. 次の一歩",
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
# 1. 課題1：母集団・分割・ベースライン
# ------------------------------------------------------------------
summary = explore.summary()
for key, expected in EXPECTED_COUNTS.items():
    check(f"件数: {key}", int(summary[key]), expected)
for key, expected in EXPECTED_RATES.items():
    check_close(f"正例率: {key}", float(summary[key]), expected)
check("訓練 + 評価が母集団と一致すること", summary["n_train"] + summary["n_test"], summary["n_rows"])
check(
    "正例の合計が母集団のキャンセル件数と一致すること",
    summary["n_train_positive"] + summary["n_test_positive"],
    summary["n_positive"],
)

baseline = summary["baseline"]
check_close("ベースラインの accuracy", baseline["accuracy"], 0.9640)
check_close("ベースラインの ROC AUC", baseline["roc_auc"], 0.5000, tol=1e-9)
check_close("ベースラインの PR-AUC（= 正例率）", baseline["pr_auc"], 0.0360)

# ------------------------------------------------------------------
# 2. 課題2：基準モデルの指標と混同行列
# ------------------------------------------------------------------
scores = model.scores()
for key, expected in EXPECTED_SCORES["plain"].items():
    check_close(f"基準モデルの {key}", scores[key], expected)
check_close("基準モデルの Brier スコア", scores["brier"], EXPECTED_BRIER["plain"], tol=BRIER_TOLERANCE)
check_close("ROC AUC のベースラインからの伸び", scores["roc_gain"], 0.2911)
check_close("PR-AUC がベースラインの何倍か", scores["pr_lift"], 5.07, tol=0.1)
check_close("accuracy のベースラインとの差", scores["accuracy_gap"], 0.0, tol=1e-12)
check_close("予測確率の平均と実際の正例率の差", abs(scores["mean_proba"] - scores["positive_rate"]), 0.0)
check("ROC AUC が PR-AUC より大きいこと", bool(scores["roc_auc"] > scores["pr_auc"]), True)

parts = scores["parts"]
for key, expected in EXPECTED_CONFUSION.items():
    check(f"混同行列の {key.upper()}", parts[key], expected)
check("4 象限の合計が評価データの件数と一致すること", sum(parts.values()), 15008)
check("陽性と予測した件数（FP + TP）", parts["fp"] + parts["tp"], 58)
check("正解した件数がベースラインと同じ 14,467 件であること", parts["tn"] + parts["tp"], 14467)

# ------------------------------------------------------------------
# 3. 課題3・課題7：閾値の表と、対応できる件数からの逆算
# ------------------------------------------------------------------
plan = thresholds.capacity_plan()
check("連絡枠（月あたり）", plan["capacity"], 400)
check("連絡枠が定数から計算されていること", MONTHLY_CAPACITY, 400)
check("閾値の表の行数", len(plan["rows"]), 4)
for row, expected in zip(plan["rows"], EXPECTED_THRESHOLDS):
    threshold, precision, recall, f1, n_positive, tp, fn, calls, calls_text = expected
    check_close(f"閾値 {threshold} の閾値そのもの", row["threshold"], threshold, tol=1e-9)
    check_close(f"閾値 {threshold} の適合率", row["precision"], precision)
    check_close(f"閾値 {threshold} の再現率", row["recall"], recall)
    check_close(f"閾値 {threshold} の F1", row["f1"], f1)
    check(f"閾値 {threshold} で陽性と予測した件数", row["n_positive"], n_positive)
    check(f"閾値 {threshold} で捕まえた件数", row["tp"], tp)
    check(f"閾値 {threshold} で見逃した件数", row["fn"], fn)
    check_close(f"閾値 {threshold} で 1 件捕まえるのに必要な連絡", row["calls_per_catch"], calls, tol=0.1)
    check(f"閾値 {threshold} の連絡件数の表示", format_calls(row["calls_per_catch"]), calls_text)
    check(f"閾値 {threshold} が枠に収まるか", row["fits"], n_positive <= 400)

check_close("閾値 0.1 のときの枠に対する倍率", plan["rows"][0]["load_ratio"], 3.35, tol=0.01)
check("閾値 0.2 が枠を超える件数", plan["rows"][1]["gap"], 54)
check("閾値 0.3 の余り", plan["rows"][2]["gap"], 180)
check("閾値 0.5 の余り", plan["rows"][3]["gap"], 342)

chosen = plan["chosen"]
check("選んだ閾値", round(chosen["threshold"], 2), 0.3)
check("選んだ閾値で陽性と予測した件数", chosen["n_positive"], 220)
check("選んだ閾値で捕まえた件数", chosen["tp"], 78)
check("選んだ閾値で見逃した件数", chosen["fn"], 463)
check("選んだ閾値で空振りした件数", chosen["fp"], 142)
check_close("選んだ閾値の適合率", chosen["precision"], 0.3545)
check_close("選んだ閾値の再現率", chosen["recall"], 0.1442)
check("F1 がいちばん高い閾値（採用しない）", round(plan["best_f1"]["threshold"], 2), 0.1)
check(
    "F1 最大の閾値は枠に収まらないこと",
    bool(plan["best_f1"]["n_positive"] > plan["capacity"]),
    True,
)

doubled = thresholds.capacity_plan(MONTHLY_CAPACITY * 2)
check("枠を 2 倍にしたときの枠", doubled["capacity"], 800)
check("枠を 2 倍にしたときに選ぶ閾値", round(doubled["chosen"]["threshold"], 2), 0.2)
check("枠を 2 倍にしたときの陽性件数", doubled["chosen"]["n_positive"], 454)
check("枠を 2 倍にしたときに捕まえる件数", doubled["chosen"]["tp"], 113)
check("増員で増える捕まえた件数", doubled["chosen"]["tp"] - chosen["tp"], 35)

# ------------------------------------------------------------------
# 4. 課題4：増分実験（①〜⑦の 14 個の指標）
# ------------------------------------------------------------------
table = features.add_all_features(features.load_order_table())
check("特徴量をすべて足した表の行数", len(table), 60031)
check_close("past_orders の平均", float(table["past_orders"].mean()), 5.64)
check("past_orders の最大", int(table["past_orders"].max()), 55)
check("元の表と同じ並び順に戻っていること", table.index.equals(features.load_order_table().index), True)

steps = features.run_steps(table)
check("増分実験の段階の数", len(steps), 7)
for step, expected in zip(steps, EXPECTED_STEPS):
    key, n_features, roc, pr = expected
    check(f"{key} の段階の記号", step["key"], key)
    check(f"{key} の特徴量の列数", step["n_features"], n_features)
    check_close(f"{key} の ROC AUC", step["roc_auc"], roc)
    check_close(f"{key} の PR-AUC", step["pr_auc"], pr)
check(
    "基準モデル②を上回った段階は⑦だけであること",
    [step["key"] for step in steps if step["beats_base"]],
    ["⑦"],
)

rates = features.rate_report(table)
check("全体のキャンセル率", f"{rates['overall']:.2%}", "3.60%")
check("流入経路を率の高い順に並べた結果", list(rates["by_channel"]), [name for name, _ in EXPECTED_CHANNEL_RATES])
for name, expected in EXPECTED_CHANNEL_RATES:
    check(f"流入経路 {name} のキャンセル率", f"{rates['by_channel'][name]:.2%}", expected)
check("登録 7 日以内のキャンセル率", f"{rates['new']:.2%}", "12.91%")
check("それ以外のキャンセル率", f"{rates['not_new']:.2%}", "3.19%")
check("値引き 20% 以上のキャンセル率", f"{rates['big_discount']:.2%}", "6.57%")
check("曜日別キャンセル率の最小", f"{rates['weekday_min']:.2%}", "3.38%")
check("曜日別キャンセル率の最大", f"{rates['weekday_max']:.2%}", "3.84%")
check("曜日別の差が 0.5 ポイント未満であること", rates["weekday_max"] - rates["weekday_min"] < 0.005, True)

# ------------------------------------------------------------------
# 5. 課題5：層化 5 分割の交差検証
# ------------------------------------------------------------------
cv = validate.cross_check()
check("fold の数", cv["n_folds"], 5)
for row in cv["rows"]:
    check_close(f"fold {row['fold']} の検証データの正例率", row["positive_rate"], 0.0360)
    check(f"fold {row['fold']} の PR-AUC がベースラインを上回ること", bool(row["pr_auc"] > 0.0360), True)
check_close("ホールドアウトの PR-AUC", cv["holdout_pr_auc"], 0.1827)
check_close("ホールドアウトの ROC AUC", cv["holdout_roc_auc"], 0.7911)
check("どの fold もベースラインを上回ったか", cv["all_above_baseline"], True)
check("fold 間のばらつきが小さいこと", cv["stable"], True)
check("交差検証の平均がホールドアウトと近いこと", cv["consistent"], True)

# ------------------------------------------------------------------
# 6. 課題6：リークの点検
# ------------------------------------------------------------------
facts = leak_audit.audit()
check_close("⑥ の PR-AUC", facts["clean"]["pr_auc"], 0.1758)
check_close("⑦ の PR-AUC", facts["leaked"]["pr_auc"], 0.4969)
check_close("⑥ → ⑦ の ROC AUC の跳ね", facts["roc_jump"], 0.179)
# ⑥ と ⑦ の PR-AUC はそれぞれ ±0.005 の許容で検証しているため、比を取ると誤差が増幅する。
# ここでは「おおよそ 2.8 倍」が成り立つことだけを見る。
check_close("⑥ → ⑦ の PR-AUC の倍率", facts["pr_ratio"], 2.8, tol=0.15)
check("跳ねたと判定された段階", facts["suspicious_keys"], ["⑦"])
check_close("それ以外の段階の最大の増加", facts["max_other_jump"], 0.069)
check("all_time_cancels がその行の is_canceled を含むこと", facts["self_included"], True)
check("all_time_cancels が 0 の行のキャンセル率", f"{facts['zero_rows_cancel_rate']:.2%}", "0.00%")
check(
    "past_cancels が 0 の行のキャンセル率は 0 ではないこと",
    bool(facts["past_cancels_zero_rate"] > 0),
    True,
)
check("チェックリストの項目数", len(leak_audit.CHECKLIST), 5)

# ------------------------------------------------------------------
# 7. 課題8：class_weight とアンダーサンプリングの代償
# ------------------------------------------------------------------
compare = sampling.compare_sampling()
for kind, expected_scores in EXPECTED_SCORES.items():
    for key, expected in expected_scores.items():
        check_close(f"{kind} の {key}", compare["scores"][kind][key], expected)
    check_close(
        f"{kind} の Brier スコア",
        compare["scores"][kind]["brier"],
        EXPECTED_BRIER[kind],
        tol=BRIER_TOLERANCE,
    )
for key, expected in EXPECTED_UNDER_COUNTS.items():
    check(f"アンダーサンプリングの {key}", compare[key], expected)
check_close("そろえた後の正例率", compare["rate_after"], 0.5, tol=1e-9)
check("balanced が閾値 0.5 で捕まえた件数", compare["parts"]["balanced"]["tp"], 316)
check("balanced が閾値 0.5 で見逃した件数", compare["parts"]["balanced"]["fn"], 225)
check("PR-AUC は改善しないこと（balanced）", compare["pr_improved"]["balanced"], False)
check("PR-AUC は改善しないこと（under）", compare["pr_improved"]["under"], False)
check("Brier が悪化すること（balanced）", compare["brier_worse"]["balanced"], True)
check("Brier が悪化すること（under）", compare["brier_worse"]["under"], True)
check("確率の平均が正例率から離れること（balanced）", compare["mean_close"]["balanced"], False)
check("確率の平均が正例率から離れること（under）", compare["mean_close"]["under"], False)
check_close("確率の平均の倍率（balanced）", compare["mean_ratio"]["balanced"], 7.5, tol=0.1)
check_close("確率の平均の倍率（under）", compare["mean_ratio"]["under"], 10.1, tol=0.2)

# ------------------------------------------------------------------
# 8. 課題10：報告カードとレポート
# ------------------------------------------------------------------
data = report.gather()
card = data["card"]
check("報告カードに accuracy が含まれないこと", "accuracy" in card, False)
check_close("報告カードの PR-AUC", card["pr_auc"], 0.1827)
check_close("報告カードの PR-AUC のベースライン比", card["pr_lift"], 5.07, tol=0.1)
check_close("報告カードの ROC AUC", card["roc_auc"], 0.7911)
check_close("報告カードの閾値", card["threshold"], 0.3, tol=1e-9)
check_close("報告カードの適合率", card["precision"], 0.3545)
check_close("報告カードの再現率", card["recall"], 0.1442)
check("報告カードの陽性と予測した件数", card["n_predicted_positive"], 220)
check("報告カードの捕まえた件数", card["tp"], 78)
check("報告カードの見逃した件数", card["fn"], 463)
check("報告カードの空振りの件数", card["fp"], 142)
check("報告カードの連絡枠の余り", card["headroom"], 180)
check_close("報告カードの Brier スコア", card["brier"], EXPECTED_BRIER["plain"], tol=BRIER_TOLERANCE)
check_close("報告カードが載せない accuracy", card["accuracy_not_reported"], 0.9640)
check("陽性と予測 = 捕まえた + 空振り", card["n_predicted_positive"], card["tp"] + card["fp"])
check("捕まえた + 見逃した = 実際のキャンセル件数", card["tp"] + card["fn"], card["n_positive"])

text = report.build_report(data)
for heading in REPORT_HEADINGS:
    check(f"レポートに見出し「{heading}」があること", heading in text, True)
check("レポートに accuracy を報告しない旨が書かれていること", "accuracy は報告しない" in text, True)
check("レポートに図のファイル名が書かれていること", "outputs/mid02_pr_curve.png" in text, True)

# ------------------------------------------------------------------
# 9. すべてのスクリプトが実行でき、図とレポートが保存されること
# ------------------------------------------------------------------
modules = [explore, model, thresholds, features, validate, leak_audit, sampling, figures, report]
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):  # 各スクリプトの出力は抑制する
        for module in modules:
            module.main()
glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("図の描画で出たフォント欠落の警告の数", len(glyph_warnings), 0)

for name in figures.FIGURES:
    path = Path(OUT_DIR) / name
    size = path.stat().st_size if path.exists() else 0
    print(f"---  {name}: {size:,} バイト")
    check(f"{name} が保存され、サイズが 0 より大きいこと", size > 0, True)

report_path = Path(OUT_DIR) / report.REPORT_NAME
report_size = report_path.stat().st_size if report_path.exists() else 0
print(f"---  {report.REPORT_NAME}: {report_size:,} バイト")
check("レポートが保存され、サイズが 0 より大きいこと", report_size > 0, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("中間プロジェクト② のすべての検証に成功しました。")
