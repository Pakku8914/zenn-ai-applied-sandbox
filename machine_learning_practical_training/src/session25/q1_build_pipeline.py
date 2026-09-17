"""問題1 の解答: 前処理と学習を 1 つの Pipeline にまとめる。

実行:
    docker compose exec lab python src/session25/q1_build_pipeline.py
"""

from __future__ import annotations

import numpy as np

from common import (
    auc_of,
    build_pipeline,
    features_target,
    load_review_table,
    split,
)


def analyze(df) -> dict[str, object]:
    """1 つの Pipeline を fit して、入口と出口の形をそろえて確認する。"""
    X, y = features_target(df)
    X_train, X_test, y_train, y_test = split(X, y)
    pipeline = build_pipeline().fit(X_train, y_train)

    pre = pipeline.named_steps["pre"]
    transformed_test = pre.transform(X_test)

    return {
        "n_rows": len(df),
        "n_train": len(X_train),
        "n_test": len(X_test),
        "steps": list(pipeline.named_steps),
        "region_missing_before": int(X["region"].isna().sum()),
        "region_missing_rate": float(X["region"].isna().mean()),
        "n_input": int(X_train.shape[1]),
        "n_output": int(transformed_test.shape[1]),
        "missing_after": int(np.isnan(transformed_test).sum()),
        "auc": auc_of(pipeline, X_test, y_test),
    }


def main() -> None:
    result = analyze(load_review_table())

    print(f"レビュー件数                   : {result['n_rows']:,} 件")
    print(f"訓練データ / 評価データ        : {result['n_train']:,} 件 / {result['n_test']:,} 件")
    print(f"Pipeline のステップ            : {result['steps']}")
    print(
        f"変換前の region の欠損         : {result['region_missing_before']:,} 件"
        f"（{result['region_missing_rate'] * 100:.2f}%）"
    )
    print(f"入力の列数 / 変換後の列数      : {result['n_input']} 列 / {result['n_output']} 列")
    print(f"変換後に残った欠損             : {result['missing_after']} 件")
    print(f"テストデータの ROC AUC         : {result['auc']:.4f}")


if __name__ == "__main__":
    main()
