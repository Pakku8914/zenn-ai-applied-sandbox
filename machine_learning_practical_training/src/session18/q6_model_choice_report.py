"""問題6 の解答: 木モデルの結果を、データの構造と重要度の限界から説明する報告を作る。

使い方:
    docker compose exec lab python src/session18/q6_model_choice_report.py
"""

from __future__ import annotations

from sklearn.linear_model import LogisticRegression

from common import (
    MAX_ITER,
    N_ESTIMATORS,
    RANDOM_STATE,
    SHOWCASE_DEPTH,
    baseline_scores,
    depth_table,
    feature_names,
    fit_and_evaluate,
    importance_table,
    load_review_table,
    make_forest,
    make_tree,
    pad,
    pipeline_for,
    split_xy,
)

PUBLISHED_YEAR_PVALUE = 0.2425  # セッション16 の statsmodels の結果
PRUNED_DEPTH = 5

# 生成ルールから予想される符号（セッション17 で係数の符号が一致したことを確認済み）
EXPECTED_SIGNS = {"unit_price": "負", "pages": "正", "body_length": "負"}


def main() -> None:
    X_train, X_test, y_train, y_test = split_xy(load_review_table())
    base = baseline_scores(y_test)
    trees = {row["depth"]: row for row in depth_table(X_train, y_train, X_test, y_test, depths=[PRUNED_DEPTH, None])}
    forest_pipeline, forest = fit_and_evaluate(make_forest(), X_train, y_train, X_test, y_test)
    _, logistic = fit_and_evaluate(
        LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE), X_train, y_train, X_test, y_test
    )
    names = feature_names(forest_pipeline)

    print("■ 問題6: どのモデルを選ぶかの報告")
    print(f"1. 同じ条件での比較（訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件 / 特徴量 {len(names)} 列）")
    rows = [
        ("ベースライン（全部 高評価）", base["accuracy"], base["roc_auc"]),
        ("決定木（制限なし・1 本）", trees[None]["test_accuracy"], trees[None]["test_auc"]),
        (f"決定木（深さ {PRUNED_DEPTH}・1 本）", trees[PRUNED_DEPTH]["test_accuracy"], trees[PRUNED_DEPTH]["test_auc"]),
        (f"ランダムフォレスト（{N_ESTIMATORS} 本）", forest["accuracy"], forest["roc_auc"]),
        ("ロジスティック回帰", logistic["accuracy"], logistic["roc_auc"]),
    ]
    print(f"{pad('モデル', 30)}| accuracy | ROC AUC")
    for label, accuracy, auc in rows:
        print(f"{pad(label, 30)}|  {accuracy:.4f}  | {auc:.4f}")
    print()

    print("2. ROC AUC の順位（ベースラインを除く）")
    ranking = sorted(rows[1:], key=lambda row: row[2], reverse=True)
    for rank, (label, _, auc) in enumerate(ranking, start=1):
        print(f"{rank} 位: {label}（{auc:.4f}）")
    print()

    print("3. 仮説の検証")
    print(
        f"バギングは制限なしの木を改善したか（{trees[None]['test_auc']:.4f} → {forest['roc_auc']:.4f}）: "
        f"{forest['roc_auc'] > trees[None]['test_auc']}"
    )
    print(
        f"刈り込んだ 1 本はフォレストに勝ったか（{trees[PRUNED_DEPTH]['test_auc']:.4f} > {forest['roc_auc']:.4f}）: "
        f"{trees[PRUNED_DEPTH]['test_auc'] > forest['roc_auc']}"
    )
    print(
        f"線形モデルはフォレストに勝ったか（{logistic['roc_auc']:.4f} > {forest['roc_auc']:.4f}）: "
        f"{logistic['roc_auc'] > forest['roc_auc']}"
    )
    print(f"生成ルールから予想される符号 : {EXPECTED_SIGNS}")
    print()

    print("4. 重要度の限界")
    forest_importance = importance_table(forest_pipeline).set_index("feature")["importance"]
    tree_importance = (
        importance_table(pipeline_for(make_tree(SHOWCASE_DEPTH)).fit(X_train, y_train))
        .set_index("feature")["importance"]
    )
    print(
        f"published_year : 重要度 {forest_importance['published_year']:.4f} / "
        f"p 値 {PUBLISHED_YEAR_PVALUE:.4f}（有意でない）"
    )
    print(
        f"pages          : 深さ {SHOWCASE_DEPTH} の木 {tree_importance['pages']:.4f} → "
        f"フォレスト {forest_importance['pages']:.4f}"
    )
    print()

    print("5. 結論")
    print("星は「カテゴリ ＋ ページ数 − 価格 − 本文長」の足し算で決まるので、境目はまっすぐな平面です。")
    print("木は軸に平行な線しか引けないため、この斜めの境目を階段で近似することになります。")
    print("バギングは 1 本の木の当てずっぽうを均して大きく改善しますが、階段という制約は取り除けません。")
    print("その結果、深さ 5 に刈った 1 本や線形モデルのほうが高い ROC AUC を出しました。")
    print("重要度は「木がその列をどれだけ使ったか」の記録なので、効いている証拠として報告してはいけません。")


if __name__ == "__main__":
    main()
