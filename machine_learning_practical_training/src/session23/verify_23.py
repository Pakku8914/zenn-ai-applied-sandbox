"""セッション 23 の検証スクリプト。

「セッション23：ハイパーパラメータ探索 ― 探しても線形モデルに届かない」の本文・
練習問題・解答に載せた数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

所要時間（秒）は環境依存なので検証しません。**学習回数**は厳密に検証します。

使い方:
    docker compose exec lab python src/session23/verify_23.py
"""

from __future__ import annotations

import warnings
from pathlib import Path

from common import DATA_DIR, OUT_DIR, load_review_table, split_train_test
from default_baseline import baseline
from final_test import final
from grid_search import FIGURE_NAME as GRID_FIGURE, make_figure as make_grid_figure, search as run_grid_search
from nested_cv import cost_table, nested_scores
from q1_default_cv import analyze as analyze_q1
from q2_grid_search import analyze as analyze_q2
from q3_search_space import analyze as analyze_q3
from q4_random_search import analyze as analyze_q4, sampled_params
from q5_score_noise import analyze as analyze_q5
from q6_nested_cv import analyze as analyze_q6
from q7_search_report import CHECKS, analyze as analyze_q7
from random_search import (
    FIGURE_NAME as POINTS_FIGURE,
    make_figure as make_points_figure,
    search as run_random_search,
)
from score_noise import analyze as analyze_noise
from search_space import LINEAR_RATES, LOG_RATES, plan_table, ratios

TOLERANCE = 0.005   # 指標の許容誤差（本書共通）
TIGHT = 0.002       # 標準偏差や「差」など、もともと小さい値に使う許容誤差

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
# 1. 母集団と分割（src/verify_setup.py の 5 節・セッション22 と同じ表であること）
# ------------------------------------------------------------------
X_train, X_test, y_train, y_test = split_train_test(df)
check("高評価分類に使うレビュー件数", len(df), 14169)
check_close("高評価（星 4 以上）の割合", float(df["is_high"].mean()), 0.8167, tol=TIGHT)
check("訓練データの件数", len(X_train), 10626)
check("テストデータの件数", len(X_test), 3543)

# ------------------------------------------------------------------
# 2. 探索なし（既定値）の交差検証（本文 1 節・問題1）
# ------------------------------------------------------------------
baseline_result = baseline(df)
check_close("探索なしの交差検証の平均 ROC AUC", baseline_result["mean"], 0.8020)
check("探索なしの学習回数", baseline_result["n_fits"], 5)

q1 = analyze_q1(df)
check("問題1 の訓練データ件数", q1["n_train"], 10626)
check("問題1 のテストデータ件数", q1["n_test"], 3543)
check_close("問題1 の交差検証の平均", q1["mean"], 0.8020)
check("問題1 が数えた組み合わせ数", q1["size"], 12)
check("問題1 が数えた学習回数", q1["fits"], 60)
check("問題1 の『探索なしの何倍か』", q1["times_heavier"], 12)

# ------------------------------------------------------------------
# 3. グリッドサーチ（本文 2 節・問題2）
# ------------------------------------------------------------------
grid = run_grid_search(df)
check("グリッドの組み合わせ数", grid["n_combinations"], 12)
check("グリッドの学習回数（計算）", grid["n_fits"], 60)
check("グリッドの学習回数（実際）", grid["actual_fits"], 60)
check("cv_results_ の行数", len(grid["table"]), 12)
check("グリッドが選んだ設定", grid["best_params"], {"learning_rate": 0.05, "n_estimators": 200, "num_leaves": 7})
check_close("グリッドの best_score_", grid["best_cv"], 0.8143)
check_close("最良設定の標準偏差", grid["best_std"], 0.0105, tol=TIGHT)

EXPECTED_TOP3 = [
    ({"learning_rate": 0.05, "n_estimators": 200, "num_leaves": 7}, 0.8143, 0.0105),
    ({"learning_rate": 0.1, "n_estimators": 200, "num_leaves": 7}, 0.8120, 0.0093),
    ({"learning_rate": 0.1, "n_estimators": 50, "num_leaves": 7}, 0.8114, 0.0094),
]
for position, (params, mean, std) in enumerate(EXPECTED_TOP3, start=1):
    row = grid["table"][position - 1]
    check(
        f"上位 {position} 件目の設定",
        {key: row[key] for key in ("learning_rate", "n_estimators", "num_leaves")},
        params,
    )
    check_close(f"上位 {position} 件目の CV の平均", row["mean"], mean)
    check_close(f"上位 {position} 件目の標準偏差", row["std"], std, tol=TIGHT)

worst = grid["worst"]
check(
    "最下位の設定（既定値に近い）",
    {key: worst[key] for key in ("learning_rate", "n_estimators", "num_leaves")},
    {"learning_rate": 0.1, "n_estimators": 200, "num_leaves": 31},
)
check_close("最下位の CV の平均", worst["mean"], 0.7904)
check("最良設定の fold ごとのスコアが 5 つあること", len(grid["fold_scores"]), 5)

q2 = analyze_q2(df)
check("問題2 の学習回数（計算 / 実際）", (q2["planned_fits"], q2["actual_fits"]), (60, 60))
check("問題2 が選んだ設定", q2["best_params"], {"learning_rate": 0.05, "n_estimators": 200, "num_leaves": 7})
check_close("問題2 の best_score_", q2["best_cv"], 0.8143)
check_close("問題2 の最下位", q2["worst"]["mean"], 0.7904)
check("問題2: 上位 3 件がすべて num_leaves=7", q2["leaves7_is_best"], True)
check("問題2 の cv_results_ の行数", q2["n_results"], 12)

# ------------------------------------------------------------------
# 4. 「最良」は誤差の中で入れ替わる（本文 5 節・問題5）
# ------------------------------------------------------------------
noise = analyze_noise(grid, float(baseline_result["mean"]))
check_close("1 位 − 2 位の差", noise["gap_to_second"], 0.0023, tol=TIGHT)
check_close("1 位 − 3 位の差", noise["gap_to_third"], 0.0029, tol=TIGHT)
check("上位 3 件の差が標準偏差より小さいこと", noise["top3_within_noise"], True)
check("上位 3 件の帯がすべて重なること", noise["bands_overlap"], True)
check_close("1 位 − 最下位の差", noise["gap_to_worst"], 0.0239, tol=TIGHT)
check("1 位 − 最下位は標準偏差の 2 倍より大きいこと", noise["worst_beyond_noise"], True)
check_close("1 位 − 探索なしの差", noise["gap_to_baseline"], 0.0123, tol=TIGHT)

q5 = analyze_q5(df)
check_close("問題5 の 1 位 − 2 位", q5["gap_to_second"], 0.0023, tol=TIGHT)
check_close("問題5 の 1 位の標準偏差", q5["best_std"], 0.0105, tol=TIGHT)
check("問題5: 上位 3 件の差はばらつきの中", q5["within_noise"], True)
check("問題5 の fold ごとのスコアの数", (len(q5["first_folds"]), len(q5["second_folds"])), (5, 5))
check("問題5: fold ごとの差の最大が平均の差より大きいこと", q5["fold_gap_exceeds_mean_gap"], True)

# ------------------------------------------------------------------
# 5. ランダムサーチ（本文 4 節・問題4）
# ------------------------------------------------------------------
random_result = run_random_search(df)
check("ランダムサーチの空間の大きさ", random_result["space"], 80)
check("空間を総当たりした場合の学習回数", random_result["full_fits"], 400)
check("実際に引いた組み合わせ数", random_result["n_sampled"], 6)
check("ランダムサーチの学習回数", random_result["n_fits"], 30)
check(
    "ランダムサーチが選んだ設定",
    random_result["best_params"],
    {"learning_rate": 0.02, "n_estimators": 400, "num_leaves": 7},
)
check_close("ランダムサーチの best_score_", random_result["best_cv"], 0.8144)
check(
    "30 回のランダムサーチが 60 回のグリッドサーチと同等（差 < 0.005）",
    abs(random_result["best_cv"] - grid["best_cv"]) < TOLERANCE,
    True,
)
check("ランダムサーチの学習回数がグリッドの半分であること", random_result["n_fits"] * 2 == grid["n_fits"], True)

q4 = analyze_q4(df)
check("問題4 の学習回数", q4["n_fits"], 30)
check("問題4 が節約した学習回数", q4["fits_saved"], 30)
check("問題4 が選んだ設定", q4["best_params"], {"learning_rate": 0.02, "n_estimators": 400, "num_leaves": 7})
check_close("問題4 の best_score_", q4["best_cv"], 0.8144)
check("問題4: グリッドと同等と言えること", q4["as_good_as_grid"], True)
check("問題4: 同じ random_state なら同じ 6 通りを引くこと", q4["same_seed_same_draw"], True)
check("問題4: 別の random_state だと違う 6 通りになること", q4["other_seed_differs"], True)
check("問題4: 引いた 6 通りに最良設定が含まれること", q4["drew_the_winner"], True)
check("ParameterSampler が返す組み合わせ数", len(sampled_params()), 6)

# ------------------------------------------------------------------
# 6. 探索範囲の決め方（本文 3 節・問題3）
# ------------------------------------------------------------------
check("等比に並べた learning_rate の倍率", ratios(LOG_RATES), [2.0, 2.5, 2.0, 2.0])
check_close("等間隔に並べたときの最初の倍率", ratios(LINEAR_RATES)[0], 5.75, tol=TIGHT)
EXPECTED_PLANS = [(12, 60), (16, 80), (125, 625), (80, 400), (80, 30)]
for row, (size, fits) in zip(plan_table(), EXPECTED_PLANS):
    check(f"探索計画『{row['label']}』の組み合わせ数", row["size"], size)
    check(f"探索計画『{row['label']}』の学習回数", row["fits"], fits)

q3 = analyze_q3()
check("問題3: ① は等比と判定されること", q3["candidates"]["① 等比（対数スケール）"]["geometric"], True)
check("問題3: ② は等比でないと判定されること", q3["candidates"]["② 等間隔（線形スケール）"]["geometric"], False)
check_close("問題3: ② の最初の倍率", q3["candidates"]["② 等間隔（線形スケール）"]["ratios"][0], 5.75, tol=TIGHT)
check_close("問題3: ① の探索範囲の広さ", q3["candidates"]["① 等比（対数スケール）"]["span"], 20.0, tol=TIGHT)
check_close("問題3: ③ の探索範囲の広さ", q3["candidates"]["③ 細かすぎる等間隔"]["span"], 2.0, tol=TIGHT)
check("問題3: A の学習回数", q3["spaces"]["A 本章のグリッド（2 × 3 × 2）"]["fits"], 60)
check("問題3: B の学習回数", q3["spaces"]["B 広い空間を総当たり（4 × 5 × 4）"]["fits"], 400)
check("問題3: C の学習回数", q3["spaces"]["C B から 6 通りだけ引く"]["fits"], 30)
check("問題3: B は C の何倍か", q3["fits_ratio"], 13)

# ------------------------------------------------------------------
# 7. ネストした交差検証（本文 7 節・問題6）
# ------------------------------------------------------------------
EXPECTED_COSTS = [5, 60, 300, 305, 35]
for row, fits in zip(cost_table(), EXPECTED_COSTS):
    check(f"学習回数『{row['label']}』", row["fits"], fits)

nested = nested_scores(df)
check("ネストした交差検証の外側 fold の数", len(nested), 5)
check(
    "ネストした交差検証のスコアがすべて 0.5〜1.0 に入ること",
    all(0.5 <= float(score) <= 1.0 for score in nested),
    True,
)

q6 = analyze_q6(df)
check("問題6 の縮小版で使った行数", q6["n_sample"], 2000)
check("問題6 の外側 fold の数", q6["n_outer"], 5)
check("問題6 のスコアが妥当な範囲に入ること", q6["in_range"], True)
check("問題6 が数えた全量ネストの学習回数", q6["full_nested_fits"], 300)
check("問題6 の学習回数の表", [row["fits"] for row in q6["cost_rows"]], EXPECTED_COSTS)

# ------------------------------------------------------------------
# 8. テストデータは最後に 1 回だけ（本文 6 節・8 節・問題7）
# ------------------------------------------------------------------
check("探索の結果にテストのスコアが含まれないこと", any("test" in key for key in grid), False)
check("ランダムサーチの結果にもテストのスコアが含まれないこと", any("test" in key for key in random_result), False)

final_result = final(df, grid["best_params"])
check_close("探索後の設定のテスト ROC AUC", final_result["tuned_test"], 0.8173)
check_close("ロジスティック回帰のテスト ROC AUC", final_result["linear_test"], 0.8265)
check_close("LightGBM（探索後）− ロジスティック回帰", final_result["gap_to_linear"], -0.0092, tol=TIGHT)
check("探索してもロジスティック回帰に届かないこと", final_result["linear_wins"], True)
check(
    "交差検証（0.8143）とテスト（0.8173）の差が許容誤差の中にあること",
    abs(final_result["tuned_test"] - grid["best_cv"]) < TOLERANCE,
    True,
)

q7 = analyze_q7(df)
check("問題7 の点検表の問いの数", len(CHECKS), 6)
check("問題7 の点検表の判定の数", len(q7["checks"]), 6)
check("問題7 の点検表がすべて OK であること", q7["all_ok"], True)
check("問題7 の実験ノートの行数", len(q7["rows"]), 5)
check_close("問題7 ① 探索なしの CV", q7["rows"][0]["score"], 0.8020)
check_close("問題7 ② グリッドサーチの CV", q7["rows"][1]["score"], 0.8143)
check_close("問題7 ③ ランダムサーチの CV", q7["rows"][2]["score"], 0.8144)
check_close("問題7 ④ 探索後のテスト", q7["rows"][3]["score"], 0.8173)
check_close("問題7 ⑤ ロジスティック回帰のテスト", q7["rows"][4]["score"], 0.8265)
check("問題7 の学習回数の内訳", [row["fits"] for row in q7["rows"]], [5, 60, 30, 1, 1])
check("問題7 の合計学習回数", q7["total_fits"], 97)
check("問題7 の結論（線形モデルの勝ち）", q7["linear_wins"], True)

# ------------------------------------------------------------------
# 9. 図が保存され、日本語が豆腐（□）にならないこと
# ------------------------------------------------------------------
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    make_grid_figure(grid["table"])
    make_points_figure(grid["table"], random_result["table"])
    glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("日本語フォントの欠落警告の数", len(glyph_warnings), 0)
for name in (GRID_FIGURE, POINTS_FIGURE):
    path = OUT_DIR / name
    check(f"{name} が保存されていること", path.exists(), True)
    check(f"{name} のファイルサイズが 0 より大きいこと", path.stat().st_size > 0, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 23 のすべての検証に成功しました。")
