"""問題3 の解答：決定木の深さを変えて、過学習の始まりを表で探す。

使い方:
    docker compose exec lab python src/session15/q3_tree_depth.py
"""

from __future__ import annotations

from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.tree import DecisionTreeClassifier

from common import DEPTHS, RANDOM_STATE, depth_label, load_review_features, pad, pipeline_for, split_features

LEAF_ROWS_LIMIT = 5  # 葉 1 枚あたりの平均件数がこれを下回ったら「丸暗記」を疑う


def tree_row(depth: int | None, X_train, y_train, X_test, y_test) -> dict:
    """深さを指定した決定木を学習し、葉の数と 3 つのスコアを返す（自分で書く）。"""
    pipeline = pipeline_for(DecisionTreeClassifier(max_depth=depth, random_state=RANDOM_STATE))
    pipeline.fit(X_train, y_train)
    tree = pipeline.named_steps["model"]
    return {
        "label": depth_label(depth),
        "leaves": int(tree.get_n_leaves()),
        "train_auc": float(roc_auc_score(y_train, pipeline.predict_proba(X_train)[:, 1])),
        "test_auc": float(roc_auc_score(y_test, pipeline.predict_proba(X_test)[:, 1])),
        "test_accuracy": float(accuracy_score(y_test, pipeline.predict(X_test))),
    }


def main() -> None:
    X_train, X_test, y_train, y_test = split_features(load_review_features())
    table = [tree_row(depth, X_train, y_train, X_test, y_test) for depth in DEPTHS]

    print(f"■ 決定木の深さ（訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件）")
    print(f"{pad('深さ', 8)} | 葉の数 | 訓練 AUC | 評価 AUC | 評価 accuracy")
    for row in table:
        print(
            f"{pad(row['label'], 8)} | {row['leaves']:>6,} | {row['train_auc']:>8.4f} | "
            f"{row['test_auc']:>8.4f} | {row['test_accuracy']:>13.4f}"
        )
    print()

    best = max(table, key=lambda r: r["test_auc"])
    worst = min(table, key=lambda r: r["test_auc"])
    first_over = next(r for r in table if r["train_auc"] > r["test_auc"])
    print("■ 読み取り")
    print(f"評価 AUC が最大の深さ : {best['label']}（{best['test_auc']:.4f}）")
    print(f"評価 AUC が最小の深さ : {worst['label']}（{worst['test_auc']:.4f}）")
    print(f"訓練 AUC が最大の深さ : {max(table, key=lambda r: r['train_auc'])['label']}")
    print(f"訓練 AUC が評価 AUC を上回りはじめる深さ : {first_over['label']}")
    print(f"評価 AUC が最大の深さで、訓練と評価の差が 0.05 未満か : "
          f"{best['train_auc'] - best['test_auc'] < 0.05}")
    print()

    print("■ 葉の数の増え方")
    print(f"深さ 1 : {table[0]['leaves']:,} 枚 → 制限なし : {table[-1]['leaves']:,} 枚")
    rows_per_leaf = len(X_train) / table[-1]["leaves"]
    print(f"制限なしのとき、葉 1 枚あたりの平均件数が {LEAF_ROWS_LIMIT} 件を下回るか : "
          f"{rows_per_leaf < LEAF_ROWS_LIMIT}")
    print()

    print("■ 深さ 20 と制限なしで、訓練 AUC がほぼ 1 なのに評価 AUC が落ちる理由")
    print("葉が 2,000 枚を超えると、1 枚の葉が訓練データ数件だけを受け持つようになります。")
    print("それは規則を学んだのではなく、訓練データを覚えただけなので、覚えていない行")
    print("（評価データ）には当たりません。訓練 AUC 0.9996 は「暗記の完成度」です。")


if __name__ == "__main__":
    main()
