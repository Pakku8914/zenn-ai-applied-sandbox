"""問題1 の解答: 層化 5 分割交差検証を回し、1 回のホールドアウトと比べる。

実行:
    docker compose exec lab python src/session22/q1_cv_vs_holdout.py
"""

from __future__ import annotations

import numpy as np
from sklearn.base import clone
from sklearn.metrics import roc_auc_score

from common import (
    build_model,
    cv_auc,
    features_target,
    fmt_scores,
    holdout_auc,
    load_review_table,
    stratified_cv,
    summarize,
)


def scores_by_hand(df) -> np.ndarray:
    """cross_val_score が中で何をしているかを、手書きのループで再現する。"""
    X, y = features_target(df)
    base = build_model()
    scores = []
    for train_index, test_index in stratified_cv().split(X, y):
        # clone で「学習前の設計図」に戻す。同じ model を使い回すと前の fold の
        # 学習結果が残り、fold ごとに独立した実験にならない
        model = clone(base).fit(X.iloc[train_index], y.iloc[train_index])
        proba = model.predict_proba(X.iloc[test_index])[:, 1]
        scores.append(float(roc_auc_score(y.iloc[test_index], proba)))
    return np.asarray(scores)


def analyze(df) -> dict[str, object]:
    """交差検証・手書きループ・ホールドアウトの 3 つを並べる。"""
    scores = cv_auc(df, stratified_cv())
    manual = scores_by_hand(df)
    mean, std = summarize(scores)
    holdout = holdout_auc(df)
    return {
        "scores": scores,
        "manual": manual,
        "mean": mean,
        "std": std,
        "band": (mean - std, mean + std),
        "holdout": holdout,
        "gap": holdout - mean,
        "same_as_manual": bool(np.allclose(scores, manual, atol=1e-6)),
        "inside_range": bool(float(scores.min()) <= holdout <= float(scores.max())),
    }


def main() -> None:
    result = analyze(load_review_table())

    print("■ 1. 層化 5 分割交差検証")
    print(f"fold ごとの ROC AUC : {fmt_scores(result['scores'])}")
    print(f"平均                : {result['mean']:.4f}")
    print(f"標準偏差            : {result['std']:.4f}")
    print(f"平均 ± 標準偏差     : {result['band'][0]:.4f} 〜 {result['band'][1]:.4f}")
    print()

    print("■ 2. 手書きループで同じ値になるか")
    print(f"手書きループの ROC AUC : {fmt_scores(result['manual'])}")
    print(f"cross_val_score と一致 : {result['same_as_manual']}")
    print()

    print("■ 3. 1 回のホールドアウトとの比較")
    print(f"ホールドアウト 1 回 : {result['holdout']:.4f}")
    print(f"交差検証の平均との差: {result['gap']:+.4f}")
    print(f"fold の最小〜最大の中に入っているか: {result['inside_range']}")
    print()

    print("■ 4. 説明例")
    print("1 回の分割で出る数値は、5 つの fold のうちどれか 1 つを引いたのと同じです。")
    print("今回はたまたま高いほうの fold に近い分割を引いたので、交差検証の平均より甘く出ました。")
    print("報告するなら「平均と標準偏差」の形にして、どれくらいぶれるのかも一緒に書きます。")


if __name__ == "__main__":
    main()
