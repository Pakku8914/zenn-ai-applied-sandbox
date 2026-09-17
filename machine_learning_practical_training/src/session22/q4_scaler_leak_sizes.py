"""問題4 の解答: 前処理を分割前に当てるリークを再現し、標本サイズを変えて差を測る。

実行:
    docker compose exec lab python src/session22/q4_scaler_leak_sizes.py
"""

from __future__ import annotations

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from common import (
    MAX_ITER,
    NUMERIC,
    RANDOM_STATE,
    TEST_SIZE,
    features_target,
    load_review_table,
)
from scaler_leak import SAMPLE_SIZES, gap, gap_by_size, leaked_auc

TOLERANCE = 0.005  # 本書の許容誤差。これ未満の差は「差が出ていない」と扱う


def leaked_by_hand(df) -> float:
    """分割前に前処理を当てる、を Pipeline なしで手書きした版（道具の問題ではないと示す）。

    標準偏差は StandardScaler と同じ ddof=0 で割ります（pandas の既定は ddof=1）。
    """
    X, y = features_target(df)
    numeric = X[NUMERIC]
    scaled = (numeric - numeric.mean()) / numeric.std(ddof=0)  # 全データの平均と標準偏差
    dummies = pd.get_dummies(X["category"], dtype="float64")
    X_all = pd.concat([scaled, dummies], axis=1)
    X_train, X_test, y_train, y_test = train_test_split(
        X_all, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    model = LogisticRegression(max_iter=MAX_ITER).fit(X_train, y_train)
    return float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))


def analyze(df) -> dict[str, object]:
    """全データと 4 つの標本サイズについて、リークの有無で差が出るかを調べる。"""
    full = gap(df)
    rows = gap_by_size(df)
    by_hand = leaked_by_hand(df)
    all_gaps = [full["gap"]] + [row["gap"] for row in rows]
    return {
        "full": full,
        "rows": rows,
        "by_hand_matches": bool(abs(by_hand - leaked_auc(df)) < TOLERANCE),
        "max_abs_gap": max(abs(value) for value in all_gaps),
        "all_within_tolerance": all(abs(value) < TOLERANCE for value in all_gaps),
        # 差の符号は上がったり下がったりする（＝リークの向きすら決まっていない）
        "signs": sorted({"+" if value > 0 else "-" if value < 0 else "0" for value in all_gaps}),
    }


def main() -> None:
    result = analyze(load_review_table())
    full = result["full"]

    print("■ 1. 全データ 14,169 件")
    print(f"正しい手順 : {full['correct']:.4f}")
    print(f"リーク     : {full['leaked']:.4f}")
    print(f"差         : {full['gap']:+.4f}")
    print(f"手書きのリーク版でも同じ値になるか: {result['by_hand_matches']}")
    print()

    print("■ 2. 標本サイズを変える")
    print("    n | 正しい手順 | リーク  | 差")
    for row in result["rows"]:
        print(f"{int(row['n']):>5} |   {row['correct']:.4f}   | {row['leaked']:.4f} | {row['gap']:+.4f}")
    print()

    print("■ 3. 判定")
    print(f"調べた標本サイズ: {SAMPLE_SIZES}")
    print(f"差の絶対値の最大: {result['max_abs_gap']:.4f}")
    print(f"すべて許容誤差 {TOLERANCE} 未満か: {result['all_within_tolerance']}")
    print(f"差の符号の種類  : {result['signs']}")
    print()

    print("■ 4. 説明例")
    print("標準化は「列ごとに平均を引いて標準偏差で割る」だけの変換です。")
    print("14,169 件の平均と、そのうち 10,626 件の平均はほとんど同じ値なので、")
    print("どちらで割っても予測の順序が変わらず、ROC AUC も動きません。")
    print("差の符号が実験ごとにばらつくことも、これが「持ち上げ」ではない証拠です。")
    print()
    print("■ 5. それでも Pipeline に載せる理由")
    print("持ち上がるかどうかは前処理の種類で決まり、実行する前には分かりません。")
    print("特徴量選択やターゲットエンコーディングでは実際に大きく持ち上がります。")
    print("「安全なものも含めて全部 fold の中に閉じ込める」ほうが、判別を考えるより安く済みます。")


if __name__ == "__main__":
    main()
