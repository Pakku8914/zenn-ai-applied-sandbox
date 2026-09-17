"""セッション 14 の検証スクリプト。

「セッション14：特徴量エンジニアリング ― 足しても良くならない、を実測する」の本文・
練習問題・解答に載せた数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session14/verify_14.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from common import (
    DATA_DIR,
    add_all_features,
    add_amount_and_age,
    add_datetime_features,
    add_past_features,
    cumulative_steps,
    evaluate,
    load_order_table,
)
from date_features import make_toy as make_date_toy
from q1_date_features import build_date_features, weekday_cancel_rate
from q2_past_features import add_all_time_cancels, add_past_by_hand, make_toy as make_past_toy
from q3_ratio_features import add_amount_and_age_by_hand
from q4_feature_steps import STEPS, run_all_steps
from q5_leak_audit import CHECKLIST, audit
from q6_rate_report import rate_report

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
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:.4f}")
    if not ok:
        print(f"     期待値: {expected:.4f} ± {tol}")
        failures.append(label)


missing = [name for name in ("books", "customers", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. 母集団と、特徴量を作る前に見た「率」
# ------------------------------------------------------------------
base_df = load_order_table()
check("重複した order_id を落とした注文の行数", len(base_df), 60031)
valid = base_df.loc[base_df["is_canceled"] == 0]
check("有効注文の件数", len(valid), 57869)
amount = valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"])
check("売上合計（合計してから round）", round(float(amount.sum())), 127104442)

report = rate_report(base_df)  # 問題6 の解答コード
check("全体のキャンセル率", f"{report['overall']:.2%}", "3.60%")
check("流入経路を率の高い順に並べた結果", list(report["by_channel"]), ["SNS", "紹介", "メルマガ", "検索"])
for channel, expected in [("SNS", "6.94%"), ("紹介", "2.49%"), ("メルマガ", "2.40%"), ("検索", "2.25%")]:
    check(f"流入経路 {channel} のキャンセル率", f"{report['by_channel'][channel]:.2%}", expected)
check("流入経路のどのグループも 5,000 件を超えること", report["min_channel_count"] > 5000, True)
check("登録 7 日未満のキャンセル率", f"{report['new']:.2%}", "12.91%")
check("それ以外のキャンセル率", f"{report['not_new']:.2%}", "3.19%")
check("登録直後の倍率", f"{report['new'] / report['not_new']:.1f}", "4.0")
check("値引き 20% 以上のキャンセル率", f"{report['big_discount']:.2%}", "6.57%")
check("曜日別キャンセル率の最小", f"{report['weekday_min']:.2%}", "3.38%")
check("曜日別キャンセル率の最大", f"{report['weekday_max']:.2%}", "3.84%")
check("曜日別の差が 0.5 ポイント未満であること", report["weekday_max"] - report["weekday_min"] < 0.005, True)

# ------------------------------------------------------------------
# 2. 日時から作る特徴量（練習用データと実データ）
# ------------------------------------------------------------------
date_toy = add_datetime_features(make_date_toy())
check("練習用データの weekday", [int(v) for v in date_toy["weekday"]], [5, 0, 5, 1])
check("練習用データの month", [int(v) for v in date_toy["month"]], [1, 5, 8, 9])
check("練習用データの is_weekend", [int(v) for v in date_toy["is_weekend"]], [1, 0, 1, 0])
check("練習用データの season", list(date_toy["season"]), ["冬", "春", "夏", "秋"])
check("練習用データの基準日からの日数", [int(v) for v in date_toy["days_to_reference"]], [213, 120, 17, 0])

dated = build_date_features(base_df)  # 問題1 の解答コード
check("weekday の種類", int(dated["weekday"].nunique()), 7)
check("month の種類", int(dated["month"].nunique()), 12)
check("is_weekend の種類", int(dated["is_weekend"].nunique()), 2)
check("season の種類", int(dated["season"].nunique()), 4)
check(
    "問題1 の weekday が common と一致すること",
    dated["weekday"].equals(add_datetime_features(base_df)["weekday"]),
    True,
)

weekday_rates = weekday_cancel_rate(dated)
check("曜日別キャンセル率が 7 行であること", len(weekday_rates), 7)
check("曜日別キャンセル率の最小（問題1）", f"{weekday_rates.min():.2%}", "3.38%")
check("曜日別キャンセル率の最大（問題1）", f"{weekday_rates.max():.2%}", "3.84%")
by_flag = dated.groupby("is_weekend")["is_canceled"].mean()
check(
    "週末フラグ別の率が曜日別の帯の中に収まること",
    bool(weekday_rates.min() <= by_flag.min() and by_flag.max() <= weekday_rates.max()),
    True,
)

# ------------------------------------------------------------------
# 3. 過去だけを集計した特徴量（未来を混ぜない）
# ------------------------------------------------------------------
past_toy = add_all_time_cancels(add_past_by_hand(make_past_toy()))
check("練習用データの past_orders", [int(v) for v in past_toy["past_orders"]], [0, 1, 2, 0, 1])
check("練習用データの past_cancels", [int(v) for v in past_toy["past_cancels"]], [0, 0, 1, 0, 1])
check("練習用データの all_time_cancels", [int(v) for v in past_toy["all_time_cancels"]], [1, 1, 1, 1, 1])
check("練習用データの並び順が戻っていること", list(past_toy["order_id"]), ["T1", "T2", "T3", "T4", "T5"])
check(
    "練習用データの前回注文からの日数",
    [None if pd.isna(v) else int(v) for v in past_toy["days_since_prev_order"]],
    [None, 36, 19, None, 72],
)

past = add_all_time_cancels(add_past_by_hand(base_df))
check("元の表と同じ並び順に戻っていること", past["order_id"].equals(base_df["order_id"]), True)
check("元の表と同じ index であること", past.index.equals(base_df.index), True)
check_close("past_orders の平均", float(past["past_orders"].mean()), 5.64)
check("past_orders の最大", int(past["past_orders"].max()), 55)
check("past_orders が 0 の行数（注文が 1 件以上ある顧客の数）", int((past["past_orders"] == 0).sum()), 7654)
check("前回注文からの日数が欠損の行数", int(past["days_since_prev_order"].isna().sum()), 7654)
check("前回注文からの日数が 0 日以上であること", bool(past["days_since_prev_order"].min() >= 0), True)
check_close("all_time_cancels の平均", float(past["all_time_cancels"].mean()), 0.442, tol=0.0005)
check(
    "past_cancels が all_time_cancels を超えないこと",
    bool((past["past_cancels"] <= past["all_time_cancels"]).all()),
    True,
)
check(
    "past_cancels と all_time_cancels が同じ列ではないこと",
    bool(past["past_cancels"].equals(past["all_time_cancels"].astype("float64"))),
    False,
)
check(
    "all_time_cancels が 0 の行のキャンセル率",
    f"{past.loc[past['all_time_cancels'] == 0, 'is_canceled'].mean():.2%}",
    "0.00%",
)
check(
    "past_cancels が 0 の行のキャンセル率は 0 ではないこと",
    float(past.loc[past["past_cancels"] == 0, "is_canceled"].mean()) == 0.0,
    False,
)
check(
    "問題2 の解答が common の実装と一致すること",
    past["past_orders"].equals(add_past_features(base_df)["past_orders"]),
    True,
)
check(
    "問題3 の amount・age が common の実装と一致すること",
    add_amount_and_age_by_hand(base_df)[["amount", "age"]].equals(add_amount_and_age(base_df)[["amount", "age"]]),
    True,
)

# ------------------------------------------------------------------
# 4. 増分実験（①〜⑦）。本文の 14 個の数値をここで再計算する
# ------------------------------------------------------------------
df = add_all_features(base_df)
check("特徴量をすべて足した表の行数", len(df), 60031)
check(
    "増分実験の列の組み合わせが common と問題4 で一致すること",
    [(numeric, categorical) for _, numeric, categorical in STEPS]
    == [(numeric, categorical) for _, numeric, categorical in cumulative_steps()],
    True,
)
results = run_all_steps(df)  # 問題4 の解答コードで 7 段階を学習する

expected_steps = [
    ("①", 3, 0.7391, 0.1133),
    ("②", 5, 0.7911, 0.1827),
    ("③", 7, 0.7886, 0.1769),
    ("④", 10, 0.7878, 0.1793),
    ("⑤", 12, 0.7895, 0.1747),
    ("⑥", 14, 0.7875, 0.1758),
    ("⑦", 15, 0.9664, 0.4969),  # ⑥の 14 列に all_time_cancels を足した累積（リーク）
]
for result, (name, n_features, roc, pr) in zip(results, expected_steps):
    check(f"{name} の特徴量の列数", result["n_features"], n_features)
    check_close(f"{name} の ROC AUC", result["roc_auc"], roc)
    check_close(f"{name} の PR-AUC", result["pr_auc"], pr)

base_result = results[1]
for result, name in zip(results[2:6], ["③", "④", "⑤", "⑥"]):
    check(
        f"{name} が基準モデル ② を上回らないこと（ROC AUC）",
        result["roc_auc"] <= base_result["roc_auc"] + TOLERANCE,
        True,
    )
    check(
        f"{name} が基準モデル ② を上回らないこと（PR-AUC）",
        result["pr_auc"] <= base_result["pr_auc"] + TOLERANCE,
        True,
    )
check(
    "⑦ だけが ② より 0.10 ポイント以上高いこと（ROC AUC）",
    results[6]["roc_auc"] - base_result["roc_auc"] > 0.10,
    True,
)
# 本文に書いたリークの幅（⑥ → ⑦ で +0.179 ポイント / PR-AUC 約 2.8 倍）を確認する
check(
    "⑦ が ⑥ より ROC AUC で 0.17 ポイント以上高いこと",
    results[6]["roc_auc"] - results[5]["roc_auc"] > 0.17,
    True,
)
check(
    "⑦ の PR-AUC が ⑥ の 2.5 倍以上であること",
    results[6]["pr_auc"] / results[5]["pr_auc"] > 2.5,
    True,
)

# ------------------------------------------------------------------
# 5. 並べ替えたまま学習すると別の分割になる（本書の規約の確認）
# ------------------------------------------------------------------
numeric_step2 = ["unit_price", "quantity", "discount_rate", "days_since_signup"]
sorted_result = evaluate(df.sort_values("ordered_at"), numeric_step2, ["channel"])
check_close("元の並び順で学習した ROC AUC", base_result["roc_auc"], 0.7911)
check_close("時間順のまま学習した ROC AUC", sorted_result["roc_auc"], 0.8030)
check(
    "並び順を変えると結果が変わること",
    abs(sorted_result["roc_auc"] - base_result["roc_auc"]) > 0.005,
    True,
)

# ------------------------------------------------------------------
# 6. リークの監査（問題5 の解答コード）
# ------------------------------------------------------------------
facts = audit(df)
check("all_time_cancels が 0 の行のキャンセル率（問題5）", f"{facts['zero_rows_cancel_rate']:.2%}", "0.00%")
check("all_time_cancels がその行の is_canceled を含むこと", facts["self_included"], True)
check("自分以外のキャンセル数が past_cancels 以上であること", facts["others_ge_past"], True)
check_close("当て推量の ROC AUC", facts["chance_roc_auc"], 0.5, tol=1e-9)
check_close("当て推量の PR-AUC（評価データの正例率）", facts["chance_pr_auc"], 0.0360, tol=0.0005)
check("評価データの正例率", f"{facts['test_positive_rate']:.2%}", "3.60%")
check("チェックリストの項目数", len(CHECKLIST), 4)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 14 のすべての検証に成功しました。")
