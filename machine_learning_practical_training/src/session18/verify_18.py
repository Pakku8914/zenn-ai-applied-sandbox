"""セッション 18 の検証スクリプト。

「セッション18：決定木とランダムフォレスト」の本文・練習問題・解答に載せた数値と挙動が、
いまこの環境で再現できるかを確認します。期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session18/verify_18.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import lightgbm
import numpy as np
from sklearn.linear_model import LogisticRegression

import forest_basics
import gini_by_hand
import importance_limits
import plot_shallow_tree
import q1_gini_by_hand
import q2_depth_table
import q3_forest_vs_baseline
import q4_importance_compare
import q5_tree_structure
import q6_model_choice_report
import tree_depth_again
from common import (
    DATA_DIR,
    DEPTHS,
    MAX_ITER,
    N_ESTIMATORS,
    OUT_DIR,
    RANDOM_STATE,
    SHOWCASE_DEPTH,
    TARGET,
    baseline_scores,
    depth_table,
    feature_names,
    fit_and_evaluate,
    gini,
    importance_table,
    load_review_table,
    make_forest,
    make_tree,
    pipeline_for,
    root_split_of,
    split_xy,
    toy_candidates,
    toy_frame,
    toy_matrix,
)

TOLERANCE = 0.005  # 指標の許容誤差（本書共通）
IMPORTANCE_TOLERANCE = 0.001  # 重要度の許容誤差
EXACT_TOLERANCE = 0.0005  # トイ例（定数の表）は計算が決まるので厳しく見る

EXPECTED_NAMES = [
    "unit_price",
    "pages",
    "published_year",
    "body_length",
    "category_ビジネス",
    "category_児童書",
    "category_実用書",
    "category_小説",
    "category_技術書",
]

# 深さ, 葉の数, 訓練 AUC, 評価 AUC, 評価 accuracy（セッション15 と同じ表）
EXPECTED_DEPTHS: list[tuple[int | None, int, float, float, float]] = [
    (1, 2, 0.6492, 0.6522, 0.8168),
    (2, 4, 0.7104, 0.7205, 0.8273),
    (3, 8, 0.7487, 0.7601, 0.8273),
    (5, 31, 0.7976, 0.7867, 0.8340),
    (10, 378, 0.8788, 0.7503, 0.8143),
    (20, 2075, 0.9963, 0.6277, 0.7669),
    (None, 2376, 0.9996, 0.6125, 0.7609),
]

# 列の並び（EXPECTED_NAMES）と同じ順番で並べた feature_importances_
EXPECTED_FOREST_IMPORTANCE = [0.1793, 0.1431, 0.0707, 0.5479, 0.0042, 0.0092, 0.0236, 0.0190, 0.0030]
EXPECTED_TREE_IMPORTANCE = [0.4113, 0.0000, 0.0000, 0.4176, 0.0000, 0.0000, 0.1710, 0.0000, 0.0000]

EXPECTED_FOREST = {"accuracy": 0.7959, "roc_auc": 0.7705}
EXPECTED_LOGISTIC = {"accuracy": 0.8422, "roc_auc": 0.8265}
EXPECTED_BOOSTER_AUC = 0.7966
EXPECTED_BASELINE = {"accuracy": 0.8168, "roc_auc": 0.5000}

# 20 件のトイ例。名前, 左の件数（高/低）, 左のジニ, 右の件数（高/低）, 右のジニ, 加重平均, 減少
EXPECTED_CANDIDATES = [
    ("① unit_price <= 2000", 12, 11, 1, 0.1528, 8, 3, 5, 0.4688, 0.2792, 0.1408),
    ("② body_length <= 120", 11, 9, 2, 0.2975, 9, 5, 4, 0.4938, 0.3859, 0.0341),
    ("③ category == 実用書", 5, 1, 4, 0.3200, 15, 13, 2, 0.2311, 0.2533, 0.1667),
    ("④ unit_price <= 1750", 10, 10, 0, 0.0000, 10, 4, 6, 0.4800, 0.2400, 0.1800),
]

FIGURES = [
    "s18_gini_toy.png",
    "s18_depth_overfit.png",
    "s18_tree.png",
    "s18_importance.png",
    "s18_q5_tree.png",
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
# 1. 不純度（ジニ係数）を手でたどるトイ例
# ------------------------------------------------------------------
toy = toy_frame()
check("トイ例の件数", len(toy), 20)
check("トイ例の高評価の件数", int(toy[TARGET].sum()), 14)
check_close("トイ例の親のジニ係数", gini(toy[TARGET]), 0.4200, tol=EXACT_TOLERANCE)
check_close("ジニ係数の最大値（10 件 / 10 件）", gini([1] * 10 + [0] * 10), 0.5000, tol=EXACT_TOLERANCE)
check_close("ジニ係数の最小値（20 件 / 0 件）", gini([1] * 20), 0.0000, tol=EXACT_TOLERANCE)

candidates = toy_candidates(toy)
check("候補の分岐の数", len(candidates), len(EXPECTED_CANDIDATES))
for row, expected in zip(candidates, EXPECTED_CANDIDATES):
    name, n_left, high_left, low_left, gini_left, n_right, high_right, low_right, gini_right, weighted, decrease = expected
    check(f"{name} の名前", row["name"], name)
    check(f"{name} の左右の件数", (row["n_left"], row["n_right"]), (n_left, n_right))
    check(f"{name} の左の内訳（高/低）", (row["high_left"], row["low_left"]), (high_left, low_left))
    check(f"{name} の右の内訳（高/低）", (row["high_right"], row["low_right"]), (high_right, low_right))
    check_close(f"{name} の左のジニ", row["gini_left"], gini_left, tol=EXACT_TOLERANCE)
    check_close(f"{name} の右のジニ", row["gini_right"], gini_right, tol=EXACT_TOLERANCE)
    check_close(f"{name} の加重平均", row["weighted"], weighted, tol=EXACT_TOLERANCE)
    check_close(f"{name} のジニ係数の減少", row["decrease"], decrease, tol=EXACT_TOLERANCE)

best = max(candidates, key=lambda row: row["decrease"])
check("いちばん減少が大きい候補", best["name"], "④ unit_price <= 1750")

matrix = toy_matrix(toy)
check("トイ例を木に渡すときの列数", matrix.shape[1], 7)
root = root_split_of(matrix, toy[TARGET])
check("木が選んだ根の分岐の列", root["feature"], "unit_price")
check_close("木が選んだ根の閾値", root["threshold"], 1750.0, tol=EXACT_TOLERANCE)
check_close("木が選んだ根の親のジニ", root["parent_gini"], 0.4200, tol=EXACT_TOLERANCE)
check_close("木が選んだ根のジニ係数の減少", root["decrease"], 0.1800, tol=EXACT_TOLERANCE)
check("手で選んだ候補と木の選択が一致すること", round(root["decrease"], 4) == round(best["decrease"], 4), True)

# ------------------------------------------------------------------
# 2. 母集団と分割（前章までと同じ特徴量・同じ分割であること）
# ------------------------------------------------------------------
df = load_review_table()
X_train, X_test, y_train, y_test = split_xy(df)
check("学習に使うレビュー件数", len(df), 14169)
check("訓練データの件数", len(X_train), 10626)
check("評価データの件数", len(X_test), 3543)
check_close("正例率（全体）", float(df[TARGET].mean()), 0.8167, tol=0.0001)
check("訓練と評価に同じ行が入っていないこと", len(set(X_train.index) & set(X_test.index)), 0)

base = baseline_scores(y_test)
check_close("ベースラインの accuracy", base["accuracy"], EXPECTED_BASELINE["accuracy"], tol=0.0001)
check_close("ベースラインの ROC AUC", base["roc_auc"], EXPECTED_BASELINE["roc_auc"], tol=0.0001)

# ------------------------------------------------------------------
# 3. 決定木の深さと過学習（葉の数は完全一致で確認する）
# ------------------------------------------------------------------
table = depth_table(X_train, y_train, X_test, y_test)
check("試した深さの数", len(table), len(DEPTHS))
for row, (depth, leaves, train_auc, test_auc, accuracy) in zip(table, EXPECTED_DEPTHS):
    name = row["label"]
    check(f"深さ {name} の葉の数", row["leaves"], leaves)
    check(f"深さ {name} のノード数（葉 × 2 - 1）", row["nodes"], leaves * 2 - 1)
    check_close(f"深さ {name} の訓練 AUC", row["train_auc"], train_auc)
    check_close(f"深さ {name} の評価 AUC", row["test_auc"], test_auc)
    check_close(f"深さ {name} の評価 accuracy", row["test_accuracy"], accuracy)

check("評価 AUC がいちばん高い深さ", max(table, key=lambda r: r["test_auc"])["label"], "5")
check("訓練 AUC がいちばん高い深さ", max(table, key=lambda r: r["train_auc"])["label"], "制限なし")
check(
    "評価 accuracy がベースラインを下回る深さ",
    [r["label"] for r in table if r["test_accuracy"] < base["accuracy"]],
    ["10", "20", "制限なし"],
)
check_close("制限なしの木の葉 1 枚あたりの件数", len(X_train) / table[-1]["leaves"], 4.4722, tol=0.001)
check_close("深さ 5 の木の葉 1 枚あたりの件数", len(X_train) / table[3]["leaves"], 342.7742, tol=0.001)

# ------------------------------------------------------------------
# 4. ランダムフォレストの設定と性能
# ------------------------------------------------------------------
forest_pipeline, forest_scores = fit_and_evaluate(make_forest(), X_train, y_train, X_test, y_test)
forest = forest_pipeline.named_steps["model"]
names = feature_names(forest_pipeline)
check("前処理後の列名", names, EXPECTED_NAMES)
check("木の本数", len(forest.estimators_), N_ESTIMATORS)
check("ブートストラップ標本を使うか", forest.bootstrap, True)
check("各分岐で候補にする列の指定", forest.max_features, "sqrt")
check("各分岐で候補にする列の数", max(1, int(np.sqrt(len(names)))), 3)
check("1 本 1 本の木の深さの制限", forest.max_depth, None)
check_close(
    "ブートストラップで 1 度も選ばれない確率",
    (1 - 1 / len(X_train)) ** len(X_train),
    0.3679,
    tol=EXACT_TOLERANCE,
)
check_close("ランダムフォレストの accuracy", forest_scores["accuracy"], EXPECTED_FOREST["accuracy"])
check_close("ランダムフォレストの ROC AUC", forest_scores["roc_auc"], EXPECTED_FOREST["roc_auc"])
check(
    "ランダムフォレストの accuracy がベースラインを下回ること",
    bool(forest_scores["accuracy"] < base["accuracy"]),
    True,
)

# ------------------------------------------------------------------
# 5. 特徴量重要度（9 値ずつ・合計 1）
# ------------------------------------------------------------------
forest_importance = importance_table(forest_pipeline)
check("重要度の行数", len(forest_importance), 9)
check("重要度の列名の並び", list(forest_importance["feature"]), EXPECTED_NAMES)
check_close("フォレストの重要度の合計", float(forest_importance["importance"].sum()), 1.0, tol=EXACT_TOLERANCE)
for name, actual, expected in zip(names, forest_importance["importance"], EXPECTED_FOREST_IMPORTANCE):
    check_close(f"フォレストの重要度 {name}", float(actual), expected, tol=IMPORTANCE_TOLERANCE)

tree_pipeline = pipeline_for(make_tree(SHOWCASE_DEPTH)).fit(X_train, y_train)
tree_importance = importance_table(tree_pipeline)
check_close("浅い木の重要度の合計", float(tree_importance["importance"].sum()), 1.0, tol=EXACT_TOLERANCE)
for name, actual, expected in zip(names, tree_importance["importance"], EXPECTED_TREE_IMPORTANCE):
    check_close(f"深さ {SHOWCASE_DEPTH} の木の重要度 {name}", float(actual), expected, tol=IMPORTANCE_TOLERANCE)

used_names = list(tree_importance.loc[tree_importance["importance"] > 0, "feature"])
check("浅い木が使った列の数", len(used_names), 3)
check("浅い木が使った列", sorted(used_names), sorted(["unit_price", "body_length", "category_実用書"]))
check(
    "浅い木で重要度 0 の列",
    list(tree_importance.loc[tree_importance["importance"] == 0, "feature"]),
    ["pages", "published_year", "category_ビジネス", "category_児童書", "category_小説", "category_技術書"],
)
inner = tree_pipeline.named_steps["model"].tree_
check(
    "木の中身（tree_.feature）から数えた「使った列」が重要度と一致すること",
    {names[i] for i in inner.feature if i >= 0} == set(used_names),
    True,
)
check(
    "浅い木では 0 なのにフォレストでは 0 でない列の数",
    int(((tree_importance["importance"] == 0) & (forest_importance["importance"] > 0)).sum()),
    6,
)

# ------------------------------------------------------------------
# 6. 3 モデルの順位（ロジスティック回帰 > LightGBM > ランダムフォレスト）
# ------------------------------------------------------------------
_, logistic_scores = fit_and_evaluate(
    LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE), X_train, y_train, X_test, y_test
)
_, booster_scores = fit_and_evaluate(
    lightgbm.LGBMClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1),
    X_train,
    y_train,
    X_test,
    y_test,
)
check_close("ロジスティック回帰の accuracy", logistic_scores["accuracy"], EXPECTED_LOGISTIC["accuracy"])
check_close("ロジスティック回帰の ROC AUC", logistic_scores["roc_auc"], EXPECTED_LOGISTIC["roc_auc"])
check_close("LightGBM の ROC AUC", booster_scores["roc_auc"], EXPECTED_BOOSTER_AUC)
ranking = sorted(
    [
        ("ロジスティック回帰", logistic_scores["roc_auc"]),
        ("LightGBM", booster_scores["roc_auc"]),
        ("ランダムフォレスト", forest_scores["roc_auc"]),
    ],
    key=lambda row: row[1],
    reverse=True,
)
check("3 モデルの ROC AUC の順位", [name for name, _ in ranking], ["ロジスティック回帰", "LightGBM", "ランダムフォレスト"])
check(
    "深さ 5 に刈った 1 本がフォレストに勝つこと",
    bool(table[3]["test_auc"] > forest_scores["roc_auc"]),
    True,
)
check(
    "バギングが制限なしの 1 本を改善すること",
    bool(forest_scores["roc_auc"] > table[-1]["test_auc"]),
    True,
)
check_close("バギングによる改善幅", forest_scores["roc_auc"] - table[-1]["test_auc"], 0.1580, tol=0.001)
check_close("線形モデルとフォレストの差", logistic_scores["roc_auc"] - forest_scores["roc_auc"], 0.0560, tol=0.001)

# ------------------------------------------------------------------
# 7. 本文・練習問題のスクリプトが最後まで動き、図が保存されること
# ------------------------------------------------------------------
for name in FIGURES:
    (Path(OUT_DIR) / name).unlink(missing_ok=True)

modules = [
    # 本文のスクリプト
    gini_by_hand,
    tree_depth_again,
    plot_shallow_tree,
    forest_basics,
    importance_limits,
    # 練習問題の解答
    q1_gini_by_hand,
    q2_depth_table,
    q3_forest_vs_baseline,
    q4_importance_compare,
    q5_tree_structure,
    q6_model_choice_report,
]
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):  # 各スクリプトの出力は抑制する
        for module in modules:
            module.main()
glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("図の描画で出たフォント欠落の警告の数", len(glyph_warnings), 0)
convergence = [w for w in caught if type(w.message).__name__ == "ConvergenceWarning"]
print(f"---  収束に関する警告の数: {len(convergence)}")

for name in FIGURES:
    path = Path(OUT_DIR) / name
    size = path.stat().st_size if path.exists() else 0
    print(f"---  {name}: {size:,} バイト")
    check(f"{name} が保存され、サイズが 0 より大きいこと", size > 0, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 18 のすべての検証に成功しました。")
