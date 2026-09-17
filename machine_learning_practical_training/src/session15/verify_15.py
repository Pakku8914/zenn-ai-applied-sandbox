"""セッション 15 の検証スクリプト。

「セッション15：教師あり学習の枠組み ― 過学習と汎化」の本文・練習問題・解答に
載せた数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session15/verify_15.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import validation_curve
from sklearn.tree import DecisionTreeClassifier

import baseline
import learning_curves
import q1_split_roles
import q2_baseline
import q3_tree_depth
import q4_learning_curve
import q5_diagnose
import q6_scope_report
import split_roles
import tree_depth
from common import (
    DATA_DIR,
    DEPTHS,
    FEATURES,
    MAX_ITER,
    OUT_DIR,
    RANDOM_STATE,
    TARGET,
    depth_label,
    depth_table,
    fit_and_score,
    learning_curve_of,
    load_review_features,
    pipeline_for,
    split_features,
    split_three_way,
)

TOLERANCE = 0.005  # 指標の許容誤差（本書共通）

# 深さ, 葉の数, 訓練 AUC, 評価 AUC, 評価 accuracy
EXPECTED_DEPTHS: list[tuple[int | None, int, float, float, float]] = [
    (1, 2, 0.6492, 0.6522, 0.8168),
    (2, 4, 0.7104, 0.7205, 0.8273),
    (3, 8, 0.7487, 0.7601, 0.8273),
    (5, 31, 0.7976, 0.7867, 0.8340),
    (10, 378, 0.8788, 0.7503, 0.8143),
    (20, 2075, 0.9963, 0.6277, 0.7669),
    (None, 2376, 0.9996, 0.6125, 0.7609),
]

EXPECTED_SIZES = [566, 2267, 5667, 11335]
EXPECTED_LR_TRAIN = [0.8522, 0.8234, 0.8252, 0.8246]
EXPECTED_LR_VALID = [0.8181, 0.8229, 0.8237, 0.8240]
EXPECTED_TREE_TRAIN = [1.0000, 1.0000, 0.9998, 0.9995]
EXPECTED_TREE_VALID = [0.5949, 0.6130, 0.6031, 0.6091]

FIGURES = ["s15_tree_depth.png", "s15_learning_curve.png", "s15_q4_learning_curve.png"]

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
# 1. 母集団と 2 分割（前章までと同じ特徴量・同じ分割であること）
# ------------------------------------------------------------------
df = load_review_features()
X_train, X_test, y_train, y_test = split_features(df)
check("学習に使うレビュー件数", len(df), 14169)
check("訓練データの件数", len(X_train), 10626)
check("評価データの件数", len(X_test), 3543)
check("特徴量の列数", X_train.shape[1], 5)
check_close("正例率（全体）", float(df[TARGET].mean()), 0.8167, tol=0.0001)
check_close("正例率（訓練）", float(y_train.mean()), 0.8167, tol=0.0001)
check_close("正例率（評価）", float(y_test.mean()), 0.8168, tol=0.0001)
check("訓練と評価に同じ行が入っていないこと", len(set(X_train.index) & set(X_test.index)), 0)

# 3 分割（テストを先に取り分けてから訓練を割る）
(X_fit, y_fit), (X_valid, y_valid), (X_test3, _) = split_three_way(df)
check("3 分割の合計が母集団と一致すること", len(X_fit) + len(X_valid) + len(X_test3), len(df))
check("学習用と検証の合計が訓練データと一致すること", len(X_fit) + len(X_valid), len(X_train))
check("3 分割のテストが 2 分割の評価データと同じ行であること", X_test.index.equals(X_test3.index), True)
check_close("学習用の正例率", float(y_fit.mean()), 0.8167, tol=0.005)
check_close("検証データの正例率", float(y_valid.mean()), 0.8167, tol=0.005)

# ------------------------------------------------------------------
# 2. ベースライン（多数クラス予測）と最初のモデル
# ------------------------------------------------------------------
dummy = DummyClassifier(strategy="most_frequent", random_state=RANDOM_STATE)
logistic = LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)
base = fit_and_score(dummy, X_train, y_train, X_test, y_test)
model = fit_and_score(logistic, X_train, y_train, X_test, y_test)
check_close("ベースラインの accuracy", base["accuracy"], 0.8168, tol=0.0001)
check_close("ベースラインの ROC AUC", base["roc_auc"], 0.5000, tol=0.0001)
check_close("ベースラインの accuracy が評価データの正例率と一致すること",
            base["accuracy"] - float(y_test.mean()), 0.0, tol=0.0001)
check_close("ロジスティック回帰の accuracy", model["accuracy"], 0.8422)
check_close("ロジスティック回帰の ROC AUC", model["roc_auc"], 0.8265)
check_close("ロジスティック回帰の log loss", model["log_loss"], 0.3592)
check_close("accuracy の改善幅", model["accuracy"] - base["accuracy"], 0.0254, tol=0.0005)
check_close("ROC AUC の改善幅", model["roc_auc"] - base["roc_auc"], 0.3265)
check("accuracy の改善が 0.03 未満であること", bool(model["accuracy"] - base["accuracy"] < 0.03), True)
check("ベースラインの log loss のほうが大きいこと", bool(base["log_loss"] > model["log_loss"]), True)

# ------------------------------------------------------------------
# 3. 決定木の深さと過学習（葉の数は完全一致で確認する）
# ------------------------------------------------------------------
table = depth_table(X_train, y_train, X_test, y_test)
check("試した深さの数", len(table), len(DEPTHS))
for row, (depth, leaves, train_auc, test_auc, accuracy) in zip(table, EXPECTED_DEPTHS):
    name = depth_label(depth)
    check(f"深さ {name} の葉の数", row["leaves"], leaves)
    check_close(f"深さ {name} の訓練 AUC", row["train_auc"], train_auc)
    check_close(f"深さ {name} の評価 AUC", row["test_auc"], test_auc)
    check_close(f"深さ {name} の評価 accuracy", row["test_accuracy"], accuracy)

best = max(table, key=lambda r: r["test_auc"])
first_over = next(r for r in table if r["train_auc"] > r["test_auc"])
check("評価 AUC がいちばん高い深さ", best["label"], "5")
check("訓練 AUC がいちばん高い深さ", max(table, key=lambda r: r["train_auc"])["label"], "制限なし")
check("訓練 AUC が評価 AUC を上回りはじめる深さ", first_over["label"], "5")
check_close("深さ 1 の評価 accuracy とベースラインの差", table[0]["test_accuracy"] - base["accuracy"], 0.0,
            tol=0.0001)
shallow_tree = DecisionTreeClassifier(max_depth=1, random_state=RANDOM_STATE)
predicted = pipeline_for(shallow_tree).fit(X_train, y_train).predict(X_test)
check("深さ 1 の木がすべて高評価と予測すること", bool((predicted == 1).all()), True)
check(
    "評価 accuracy がベースラインを下回る深さ",
    [r["label"] for r in table if r["test_accuracy"] < base["accuracy"]],
    ["10", "20", "制限なし"],
)
check("葉の数が 1,000 倍以上に増えること", bool(table[-1]["leaves"] >= table[0]["leaves"] * 1000), True)
check("制限なしのとき葉 1 枚あたりが平均 5 件未満であること",
      bool(len(X_train) / table[-1]["leaves"] < 5), True)

# 診断の言葉（本文と練習問題で同じ判定になること）
check("深さ 1 の診断", tree_depth.diagnose(table[0]["train_auc"], table[0]["test_auc"]),
      "未学習（バイアスが大きい）")
check("深さ 5 の診断", tree_depth.diagnose(table[3]["train_auc"], table[3]["test_auc"]), "釣り合っている")
check("制限なしの診断", tree_depth.diagnose(table[-1]["train_auc"], table[-1]["test_auc"]),
      "過学習（バリアンスが大きい）")
labels = [q5_diagnose.diagnose(r["train_auc"], r["test_auc"]) for r in table]
check("練習問題の diagnose が本文と同じ結果になること",
      labels, [tree_depth.diagnose(r["train_auc"], r["test_auc"]) for r in table])
check("未学習と判定される深さの数", labels.count("未学習（バイアスが大きい）"), 1)
check("釣り合っていると判定される深さの数", labels.count("釣り合っている"), 3)
check("過学習と判定される深さの数", labels.count("過学習（バリアンスが大きい）"), 3)

# ------------------------------------------------------------------
# 4. 学習曲線（2 パターンの形）
# ------------------------------------------------------------------
sizes, lr_train, lr_valid = learning_curve_of(logistic, df[FEATURES], df[TARGET])
check("学習曲線の件数", sizes, EXPECTED_SIZES)
for n, actual, expected in zip(sizes, lr_train, EXPECTED_LR_TRAIN):
    check_close(f"ロジスティック回帰の訓練 AUC（{n:,} 件）", actual, expected)
for n, actual, expected in zip(sizes, lr_valid, EXPECTED_LR_VALID):
    check_close(f"ロジスティック回帰の検証 AUC（{n:,} 件）", actual, expected)

tree_sizes, tree_train, tree_valid = learning_curve_of(
    DecisionTreeClassifier(random_state=RANDOM_STATE), df[FEATURES], df[TARGET]
)
check("決定木の学習曲線の件数", tree_sizes, EXPECTED_SIZES)
for n, actual, expected in zip(tree_sizes, tree_train, EXPECTED_TREE_TRAIN):
    check_close(f"決定木の訓練 AUC（{n:,} 件）", actual, expected)
for n, actual, expected in zip(tree_sizes, tree_valid, EXPECTED_TREE_VALID):
    check_close(f"決定木の検証 AUC（{n:,} 件）", actual, expected)

check("ロジスティック回帰は 2 本が接近すること（差が 0.01 未満）",
      bool(lr_train[-1] - lr_valid[-1] < 0.01), True)
check("決定木は 2 本が開いたままであること（差が 0.30 超）",
      bool(tree_train[-1] - tree_valid[-1] > 0.30), True)
check("決定木の検証 AUC が一度もロジスティック回帰を上回らないこと",
      bool(max(tree_valid) < min(lr_valid)), True)
check("件数を 20 倍にしたロジスティック回帰の検証 AUC の伸びが 0.01 未満であること",
      bool(lr_valid[-1] - lr_valid[0] < 0.01), True)

# ------------------------------------------------------------------
# 5. 練習問題の解答スクリプトの中身（数値以外の約束）
# ------------------------------------------------------------------
parts = q1_split_roles.make_splits(df)
check("問題1 の 2 分割の件数", (len(parts["訓練"][0]), len(parts["評価"][0])), (10626, 3543))
check("問題1 の役割の割り当ての数", len(q1_split_roles.ROLES), 5)
check("問題6 の「扱わない範囲」の項目数", len(q6_scope_report.OUT_OF_SCOPE), 3)
check("問題6 の「本番前の確認」の項目数", len(q6_scope_report.BEFORE_PRODUCTION), 3)

# 解答章に載せた別解が動くこと（classification_report と validation_curve）
report_text = classification_report(
    y_test,
    pipeline_for(DummyClassifier(strategy="most_frequent", random_state=RANDOM_STATE))
    .fit(X_train, y_train)
    .predict(X_test),
    digits=4,
    zero_division=0,
)
check("別解の classification_report に accuracy 行があること", "accuracy" in report_text, True)
vc_train, vc_valid = validation_curve(
    pipeline_for(DecisionTreeClassifier(random_state=RANDOM_STATE)),
    df[FEATURES],
    df[TARGET],
    param_name="model__max_depth",
    param_range=[1, 2, 3, 5, 10, 20],
    cv=5,
    scoring="roc_auc",
    n_jobs=1,
)
check("別解の validation_curve の形", (vc_train.shape, vc_valid.shape), ((6, 5), (6, 5)))

# ------------------------------------------------------------------
# 6. 本文・練習問題のスクリプトが最後まで動き、図が保存されること
# ------------------------------------------------------------------
for name in FIGURES:
    (Path(OUT_DIR) / name).unlink(missing_ok=True)

modules = [
    # 本文のスクリプト
    split_roles,
    baseline,
    tree_depth,
    learning_curves,
    # 練習問題の解答
    q1_split_roles,
    q2_baseline,
    q3_tree_depth,
    q4_learning_curve,
    q5_diagnose,
    q6_scope_report,
]
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):  # 各スクリプトの出力は抑制する
        for module in modules:
            module.main()
glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("図の描画で出たフォント欠落の警告の数", len(glyph_warnings), 0)
# 収束の警告は件数だけ表示する（出た場合は max_iter を増やす合図。隠さず残す）
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
print("セッション 15 のすべての検証に成功しました。")
