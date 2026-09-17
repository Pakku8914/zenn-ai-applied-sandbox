"""バギングとランダムフォレストの設定を確かめ、1 本の木・線形モデルと同じ条件で比べる。

使い方:
    docker compose exec lab python src/session18/forest_basics.py
"""

from __future__ import annotations

import lightgbm
import numpy as np
from sklearn.linear_model import LogisticRegression

from common import (
    MAX_ITER,
    N_ESTIMATORS,
    RANDOM_STATE,
    baseline_scores,
    depth_table,
    feature_names,
    fit_and_evaluate,
    load_review_table,
    make_forest,
    pad,
    split_xy,
)


def main() -> None:
    X_train, X_test, y_train, y_test = split_xy(load_review_table())

    # ------------------------------------------------------------------
    # 1. ランダムフォレストの設定（何が「ランダム」なのかを確かめる）
    # ------------------------------------------------------------------
    pipeline, forest_scores = fit_and_evaluate(make_forest(), X_train, y_train, X_test, y_test)
    forest = pipeline.named_steps["model"]
    names = feature_names(pipeline)
    per_split = max(1, int(np.sqrt(len(names))))

    print("■ ランダムフォレストの設定を確かめる")
    print(f"木の本数（n_estimators）: {forest.n_estimators}")
    print(f"実際に学習された木の本数: {len(forest.estimators_)}")
    print(f"ブートストラップ標本を使うか（bootstrap）: {forest.bootstrap}")
    print(
        f"各分岐で候補にする列の数（max_features={forest.max_features!r}）: "
        f"int(sqrt({len(names)})) = {per_split} 列"
    )
    print(f"1 本 1 本の木の深さの制限（max_depth）: {forest.max_depth}")
    print()

    # ------------------------------------------------------------------
    # 2. ブートストラップ標本の性質（乱数を引かずに計算で出せる）
    # ------------------------------------------------------------------
    n = len(X_train)
    never_picked = (1 - 1 / n) ** n
    print("■ ブートストラップ標本のしくみ（乱数を引かずに確率で確かめる）")
    print(f"{n:,} 件から {n:,} 件を「重複あり」で引き直す")
    print(f"ある 1 件が 1 度も選ばれない確率 = (1 - 1/{n:,})^{n:,} = {never_picked:.4f}")
    print(f"→ 1 本の木が見る「異なる行」の割合 = {1 - never_picked:.4f}")
    print("  残りはその木には渡りません（だから木ごとに違う木になります）")
    print()

    # ------------------------------------------------------------------
    # 3. 同じ条件でモデルを並べる（比較の条件を 1 つだけに絞る）
    # ------------------------------------------------------------------
    trees = {row["depth"]: row for row in depth_table(X_train, y_train, X_test, y_test, depths=[5, None])}
    base = baseline_scores(y_test)
    _, booster_scores = fit_and_evaluate(
        lightgbm.LGBMClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1),
        X_train,
        y_train,
        X_test,
        y_test,
    )
    _, logistic_scores = fit_and_evaluate(
        LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE),
        X_train,
        y_train,
        X_test,
        y_test,
    )

    rows = [
        ("ベースライン（全部 高評価）", base["accuracy"], base["roc_auc"]),
        ("決定木（制限なし・1 本）", trees[None]["test_accuracy"], trees[None]["test_auc"]),
        ("決定木（深さ 5・1 本）", trees[5]["test_accuracy"], trees[5]["test_auc"]),
        (f"ランダムフォレスト（{N_ESTIMATORS} 本）", forest_scores["accuracy"], forest_scores["roc_auc"]),
        (f"LightGBM（{N_ESTIMATORS} 本・次章）", booster_scores["accuracy"], booster_scores["roc_auc"]),
        ("ロジスティック回帰", logistic_scores["accuracy"], logistic_scores["roc_auc"]),
    ]

    print(f"■ 同じ特徴量 {len(names)} 列・同じ分割で比べる（評価データ {len(X_test):,} 件）")
    print(f"{pad('モデル', 30)}| accuracy | ROC AUC")
    for label, accuracy, auc in rows:
        print(f"{pad(label, 30)}|  {accuracy:.4f}  | {auc:.4f}")
    print()

    ranking = sorted(rows[1:], key=lambda row: row[2], reverse=True)
    print("■ ROC AUC の順位（ベースラインを除く）")
    for rank, (label, _, auc) in enumerate(ranking, start=1):
        print(f"{rank} 位: {label}（{auc:.4f}）")
    print()

    # ------------------------------------------------------------------
    # 4. バギングは効いたのか / それでも勝てない相手は誰か
    # ------------------------------------------------------------------
    single = trees[None]["test_auc"]
    pruned = trees[5]["test_auc"]
    print("■ バギングは効いたのか（同じ「制限なしの木」を 1 本 → 200 本）")
    print(f"決定木（制限なし・1 本）       AUC {single:.4f}")
    print(f"ランダムフォレスト（200 本）   AUC {forest_scores['roc_auc']:.4f}")
    print(f"差 {forest_scores['roc_auc'] - single:+.4f} → 束ねるだけで大きく上がった")
    print()
    print("■ それでもフォレストに勝つ相手")
    print(f"決定木（深さ 5 に刈った 1 本）  AUC {pruned:.4f}（フォレストとの差 {pruned - forest_scores['roc_auc']:+.4f}）")
    print(
        f"ロジスティック回帰             AUC {logistic_scores['roc_auc']:.4f}"
        f"（フォレストとの差 {logistic_scores['roc_auc'] - forest_scores['roc_auc']:+.4f}）"
    )
    print()
    print("■ accuracy の注意")
    print(f"ベースライン（何も学習しない）の accuracy {base['accuracy']:.4f}")
    print(f"ランダムフォレストの accuracy           {forest_scores['accuracy']:.4f}")
    print(
        "→ ランダムフォレストは accuracy ではベースラインに負けています。"
        f"（{forest_scores['accuracy'] - base['accuracy']:+.4f}）"
    )


if __name__ == "__main__":
    main()
