"""問題5 の解答: predict_proba を係数と切片から手で再現する。

使い方:
    docker compose exec lab python src/session17/q5_manual_proba.py
"""

from __future__ import annotations

import numpy as np

from common import DEFAULT_THRESHOLD, fit_model, load_review_table, prepare, sigmoid, split_xy

HEAD = 5  # 先頭何件で確かめるか
TOLERANCE = 1e-9  # 「一致した」と見なす差の上限


def manual_logit(X_t, model) -> np.ndarray:
    """特徴量の行列と係数の内積に切片を足して、対数オッズを自分で計算する。"""
    return X_t @ model.coef_[0] + model.intercept_[0]


def manual_proba(X_t, model) -> np.ndarray:
    """対数オッズをシグモイドに通して確率にする（これが predict_proba の中身）。"""
    return sigmoid(manual_logit(X_t, model))


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    model = fit_model(train, y_train)

    mine = manual_proba(test, model)
    theirs = model.predict_proba(test)[:, 1]
    logits = manual_logit(test, model)

    print(f"■ 先頭 {HEAD} 件を手計算と predict_proba で比べる（対数オッズは小数第 1 位まで表示）")
    print("対数オッズ | 手計算の確率 | predict_proba | predict")
    for i in range(HEAD):
        print(
            f"     {logits[i]:+.1f}  |    {mine[i]:.4f}    |    {theirs[i]:.4f}     |"
            f"    {int(theirs[i] >= DEFAULT_THRESHOLD)}"
        )
    print()

    print("■ 評価データの全件で一致しているか")
    gap = float(np.abs(mine - theirs).max())
    print(f"手計算と predict_proba の最大の差が {TOLERANCE:.0e} より小さいか: {gap < TOLERANCE}")
    decision_gap = float(np.abs(model.decision_function(test) - logits).max())
    print(f"decision_function が対数オッズと一致するか: {decision_gap < TOLERANCE}")
    print(f"手計算の確率を 0.5 で切った結果が predict と完全に一致するか: "
          f"{bool(((mine >= DEFAULT_THRESHOLD).astype('int64') == model.predict(test)).all())}")
    print()
    print("→ predict_proba は「係数との足し算（対数オッズ）→ シグモイド」をしているだけです。")
    print("   predict はその確率を 0.5 で切っているだけなので、閾値を変えたいなら自分で切ります。")


if __name__ == "__main__":
    main()
