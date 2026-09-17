"""セッション 12 の検証スクリプト。

「セッション12：外れ値とスケーリング ― 捨てるか変えるかを決める」の本文・練習問題・解答に
載せた数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session12/verify_12.py
"""

from __future__ import annotations

import warnings
from pathlib import Path

import lightgbm
import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from common import (
    BULK_THRESHOLD,
    CLIP_UPPER,
    DATA_DIR,
    NUMERIC_FEATURES,
    RANDOM_STATE,
    TEST_SIZE,
    add_amount,
    load_orders,
    load_review_features,
    make_design_matrix,
    outlier_bounds,
    outlier_mask,
    scale_numeric,
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
# 1. 母集団と quantity の要約（セッション9 の値がそのまま引き継がれること）
# ------------------------------------------------------------------
orders = load_orders()
quantity = orders["quantity"]
check("重複を除いた注文の行数", len(orders), 60031)
check_close("quantity の平均", float(quantity.mean()), 1.2741)
check("quantity の中央値", float(quantity.median()), 1.0)
check("quantity の最頻値", int(quantity.mode().iloc[0]), 1)
check_close("quantity の標準偏差", float(quantity.std()), 1.3237)
check("quantity の最大値", int(quantity.max()), 39)
check("4〜14 冊の注文", int(quantity.between(4, 14).sum()), 0)
check("1〜3 冊の注文", int(quantity.between(1, 3).sum()), 59913)

# ------------------------------------------------------------------
# 2. IQR 法は破綻し、3σ 法は仕込みと一致する
# ------------------------------------------------------------------
q1, q3 = float(quantity.quantile(0.25)), float(quantity.quantile(0.75))
check("Q1", q1, 1.0)
check("Q3", q3, 1.0)
check("IQR", q3 - q1, 0.0)
iqr_lower, iqr_upper = outlier_bounds(quantity, "iqr")
check_close("IQR 法の上限", iqr_upper, 1.0, tol=1e-9)
check_close("IQR 法の下限", iqr_lower, 1.0, tol=1e-9)
iqr_mask = outlier_mask(quantity, "iqr")
check("IQR 法が外れ値とする件数", int(iqr_mask.sum()), 10914)
check("IQR 法が外れ値とする割合の表示", f"{iqr_mask.mean():.1%}", "18.2%")

sigma_lower, sigma_upper = outlier_bounds(quantity, "sigma")
check_close("3σ 法の上限", sigma_upper, 5.2453)
check("3σ 法の下限が負であること", sigma_lower < 0, True)
sigma_mask = outlier_mask(quantity, "sigma")
check("3σ 法が外れ値とする件数", int(sigma_mask.sum()), 118)
check("3σ 法が外れ値とする割合の表示", f"{sigma_mask.mean():.1%}", "0.2%")

bulk = quantity >= BULK_THRESHOLD
check(f"{BULK_THRESHOLD} 冊以上の件数", int(bulk.sum()), 118)
check("3σ 法の結果がまとめ買いと完全に一致すること", bool(sigma_mask.equals(bulk)), True)
check("IQR 法だけが外れ値とした件数", int((iqr_mask & ~sigma_mask).sum()), 10914 - 118)
check(
    "IQR 法だけが外れ値とした冊数の種類",
    [int(v) for v in sorted(quantity.loc[iqr_mask & ~sigma_mask].unique())],
    [2, 3],
)

try:
    outlier_bounds(quantity, "3sigma")
except ValueError as error:
    check("未知の method で ValueError になること", type(error).__name__, "ValueError")
else:
    check("未知の method で ValueError になること", "例外が出なかった", "ValueError")

# ------------------------------------------------------------------
# 3. 捨てる判断の材料（売上構成比とキャンセル率）
# ------------------------------------------------------------------
valid = add_amount(orders)
check("有効注文の件数", len(valid), 57869)
total_amount = float(valid["amount"].sum())
bulk_amount = float(valid.loc[valid["quantity"] >= BULK_THRESHOLD, "amount"].sum())
check("売上合計（合計してから round）", round(total_amount), 127104442)
check("まとめ買いの売上（合計してから round）", round(bulk_amount), 2895666)
check_close("売上に占める割合", bulk_amount / total_amount, 0.0228, tol=0.0001)
check("売上に占める割合の表示", f"{bulk_amount / total_amount:.2%}", "2.28%")

bulk_cancel_rate = float(orders.loc[bulk, "is_canceled"].mean())
all_cancel_rate = float(orders["is_canceled"].mean())
check_close("まとめ買いのキャンセル率", bulk_cancel_rate, 0.3898, tol=0.0001)
check("まとめ買いのキャンセル率の表示", f"{bulk_cancel_rate:.2%}", "38.98%")
check("まとめ買いのキャンセル件数", int(orders.loc[bulk, "is_canceled"].sum()), 46)
check("全体のキャンセル率の表示", f"{all_cancel_rate:.2%}", "3.60%")
check("キャンセル率の倍率の表示", f"{bulk_cancel_rate / all_cancel_rate:.1f}", "10.8")

# ------------------------------------------------------------------
# 4. 処置ごとの平均と歪度
# ------------------------------------------------------------------
kept = quantity.loc[quantity < BULK_THRESHOLD]
clipped = quantity.clip(upper=CLIP_UPPER)
logged = np.log1p(quantity)
check("除外後の行数", len(kept), 59913)
check("クリップ後の行数", len(clipped), 60031)
check_close("除外後の平均", float(kept.mean()), 1.2216)
check_close("クリップ後の平均", float(clipped.mean()), 1.2251)
check("除外後の最大値", int(kept.max()), 3)
check("クリップ後の最大値", int(clipped.max()), CLIP_UPPER)
check_close("quantity の歪度", float(quantity.skew()), 19.4354)
check_close("log1p 変換後の歪度", float(logged.skew()), 4.3653)
check("除外後の歪度が 5 未満であること", bool(kept.skew() < 5), True)
check("クリップ後の歪度が 5 未満であること", bool(clipped.skew() < 5), True)
for books_count, expected_log in [(1, 0.6931), (3, 1.3863), (15, 2.7726), (39, 3.6889)]:
    check_close(f"log1p({books_count})", float(np.log1p(books_count)), expected_log, tol=0.0001)
check("log1p が順序を変えないこと", bool((logged.rank() == quantity.rank()).all()), True)

# ------------------------------------------------------------------
# 5. スケーリングの効果（高評価レビューの分類）
# ------------------------------------------------------------------
df = load_review_features()
X, y = make_design_matrix(df), df["is_high"]
check("特徴量の列数", X.shape[1], 9)
check("学習に使うレビュー件数", len(X), 14169)
check_close("正例率", float(y.mean()), 0.8167)
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
)
check("訓練データの件数", len(X_train), 10626)
check("評価データの件数", len(X_test), 3543)
check_close(
    "基準線（全員を高評価と予測）の ROC AUC",
    float(roc_auc_score(y_test, np.full(len(y_test), 0.9))),
    0.5,
    tol=1e-9,
)

expected_auc = {
    "none": (0.8267, 0.7938),
    "standard": (0.8265, 0.7966),
    "minmax": (0.8258, 0.7972),
}
scaled_sets = {}
for name, (auc_lr_expected, auc_gbm_expected) in expected_auc.items():
    train, test = scale_numeric(X_train, X_test, name)
    scaled_sets[name] = (train, test)
    lr = LogisticRegression(max_iter=1000, random_state=RANDOM_STATE).fit(train, y_train)
    gbm = lightgbm.LGBMClassifier(n_estimators=200, random_state=RANDOM_STATE, verbose=-1).fit(train, y_train)
    check_close(f"{name}: ロジスティック回帰の ROC AUC", float(roc_auc_score(y_test, lr.predict_proba(test)[:, 1])), auc_lr_expected)
    check_close(f"{name}: LightGBM の ROC AUC", float(roc_auc_score(y_test, gbm.predict_proba(test)[:, 1])), auc_gbm_expected)

standard_train = scaled_sets["standard"][0]["unit_price"]
standard_test = scaled_sets["standard"][1]["unit_price"]
minmax_train = scaled_sets["minmax"][0]["unit_price"]
check("標準化後の訓練データの平均が 0 であること", bool(np.isclose(standard_train.mean(), 0.0)), True)
check("標準化後の訓練データの標準偏差が 1 であること", bool(np.isclose(standard_train.std(ddof=0), 1.0)), True)
check("正規化後の訓練データの最小", f"{minmax_train.min():.4f}", "0.0000")
check("正規化後の訓練データの最大", f"{minmax_train.max():.4f}", "1.0000")
check("検証データの平均はちょうど 0 にならないこと", bool(standard_test.mean() == 0.0), False)
check("スケーリングなしでは値がそのままであること", bool(scaled_sets["none"][0].equals(X_train)), True)

# ------------------------------------------------------------------
# 6. スケーリングは精度ではなく収束に効く
# ------------------------------------------------------------------
for name, expect_warning in [("none", True), ("standard", False)]:
    train, _ = scaled_sets[name]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = LogisticRegression(max_iter=100, random_state=RANDOM_STATE).fit(train, y_train)
    warned = any(issubclass(w.category, ConvergenceWarning) for w in caught)
    check(f"{name}: max_iter=100 で ConvergenceWarning が出るか", warned, expect_warning)
    check(f"{name}: max_iter=100 で反復回数が上限に達するか", int(model.n_iter_[0]) >= 100, expect_warning)

# ------------------------------------------------------------------
# 7. fit は訓練データだけ、検証データは transform だけ
# ------------------------------------------------------------------
toy_train = np.array([[100.0], [200.0], [300.0]])
toy_test = np.array([[400.0]])
toy_scaler = StandardScaler().fit(toy_train)
check_close("おもちゃデータの平均", float(toy_scaler.mean_[0]), 200.0, tol=1e-9)
check_close("おもちゃデータの標準偏差", float(toy_scaler.scale_[0]), 81.6497, tol=0.0001)
check(
    "訓練データを変換した結果",
    [round(float(v), 4) for v in toy_scaler.transform(toy_train).ravel()],
    [-1.2247, 0.0, 1.2247],
)
check_close("正しい手順で変換した 400", float(toy_scaler.transform(toy_test)[0][0]), 2.4495, tol=0.0001)
check_close(
    "検証データに fit_transform した 400",
    float(StandardScaler().fit_transform(toy_test)[0][0]),
    0.0,
    tol=1e-9,
)
check_close(
    "MinMaxScaler で変換した 400",
    float(MinMaxScaler().fit(toy_train).transform(toy_test)[0][0]),
    1.5,
    tol=1e-9,
)

fit_on_train = StandardScaler().fit(X_train[NUMERIC_FEATURES])
fit_on_all = StandardScaler().fit(X[NUMERIC_FEATURES])
check(
    "訓練で fit した平均と全データで fit した平均が違うこと",
    bool(fit_on_train.mean_[0] == fit_on_all.mean_[0]),
    False,
)


def probabilities_with(scaler: StandardScaler) -> np.ndarray:
    train, test = X_train.copy(), X_test.copy()
    train[NUMERIC_FEATURES] = scaler.transform(X_train[NUMERIC_FEATURES])
    test[NUMERIC_FEATURES] = scaler.transform(X_test[NUMERIC_FEATURES])
    model = LogisticRegression(max_iter=1000, random_state=RANDOM_STATE).fit(train, y_train)
    return model.predict_proba(test)[:, 1]


proba_correct = probabilities_with(fit_on_train)
proba_leaked = probabilities_with(fit_on_all)
check("2 つの手順で予測確率が完全に一致しないこと", bool(np.array_equal(proba_correct, proba_leaked)), False)
auc_correct = float(roc_auc_score(y_test, proba_correct))
auc_leaked = float(roc_auc_score(y_test, proba_leaked))
check_close("正しい手順の ROC AUC", auc_correct, 0.8265)
check("2 つの手順の AUC の差が 0.005 未満であること", bool(abs(auc_correct - auc_leaked) < 0.005), True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 12 のすべての検証に成功しました。")
