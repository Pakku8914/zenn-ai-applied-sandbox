"""問題2 の解答: 決定木の深さを変えて、葉の細かさと過学習の関係を表にする。

使い方:
    docker compose exec lab python src/session18/q2_depth_table.py
"""

from __future__ import annotations

from sklearn.metrics import accuracy_score, roc_auc_score

from common import DEPTHS, baseline_scores, depth_label, load_review_table, make_tree, pad, pipeline_for, split_xy

GAP_LIMIT = 0.05  # 訓練 AUC と評価 AUC の差がこれを超えたら過学習を疑う（セッション15 と同じ基準）


def scores_for_depth(depth: int | None, X_train, y_train, X_test, y_test) -> dict:
    """深さを 1 つ決めて木を学習し、葉の数と 3 つのスコアを返す。"""
    pipeline = pipeline_for(make_tree(depth)).fit(X_train, y_train)
    tree = pipeline.named_steps["model"]
    return {
        "label": depth_label(depth),
        "leaves": int(tree.get_n_leaves()),
        "nodes": int(tree.tree_.node_count),
        "train_auc": float(roc_auc_score(y_train, pipeline.predict_proba(X_train)[:, 1])),
        "test_auc": float(roc_auc_score(y_test, pipeline.predict_proba(X_test)[:, 1])),
        "test_accuracy": float(accuracy_score(y_test, pipeline.predict(X_test))),
    }


def main() -> None:
    X_train, X_test, y_train, y_test = split_xy(load_review_table())
    base = baseline_scores(y_test)
    table = [scores_for_depth(depth, X_train, y_train, X_test, y_test) for depth in DEPTHS]

    print(f"■ 問題2: 深さと過学習（訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件）")
    print(f"{pad('深さ', 9)}| 葉の数 | 葉 1 枚あたり | 訓練 AUC | 評価 AUC | 判定")
    for row in table:
        verdict = "過学習" if row["train_auc"] - row["test_auc"] > GAP_LIMIT else "釣り合い"
        print(
            f"{pad(row['label'], 9)}| {row['leaves']:>6,} | {len(X_train) / row['leaves']:>11,.1f} 件 | "
            f"{row['train_auc']:>8.4f} | {row['test_auc']:>8.4f} | {verdict}"
        )
    print()

    best = max(table, key=lambda row: row["test_auc"])
    over = [row for row in table if row["train_auc"] - row["test_auc"] > GAP_LIMIT]
    print("■ 読み取り")
    print(f"評価 AUC がいちばん高い深さ : {best['label']}（{best['test_auc']:.4f}・葉 {best['leaves']} 枚）")
    print(f"差が {GAP_LIMIT} を超える（過学習を疑う）深さ : {' / '.join(row['label'] for row in over)}")
    print(f"ベースラインの accuracy {base['accuracy']:.4f} を下回る深さ : "
          f"{' / '.join(row['label'] for row in table if row['test_accuracy'] < base['accuracy'])}")
    print(f"葉の数 : {table[0]['leaves']:,} 枚 → {table[-1]['leaves']:,} 枚")
    print(f"ノードの数 : {table[0]['nodes']:,} 個 → {table[-1]['nodes']:,} 個")
    print()

    print("■ 結論（2 文）")
    print(
        f"深くするほど葉 1 枚が見る件数が減り、最後は {len(X_train) / table[-1]['leaves']:.1f} 件の"
        "意見から予測を決めることになります。"
    )
    print("訓練データでは当たるようになりますが、その細かさは未知のデータでは通用せず、評価 AUC は下がります。")


if __name__ == "__main__":
    main()
