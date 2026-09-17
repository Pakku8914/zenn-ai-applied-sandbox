"""Pipeline と ColumnTransformer の最小構成（本文 1 節・2 節）。

実行:
    docker compose exec lab python src/session25/pipeline_basics.py
"""

from __future__ import annotations

from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from common import (
    CATEGORICAL,
    MAX_ITER,
    NUMERIC,
    RANDOM_STATE,
    auc_of,
    build_pipeline,
    features_target,
    load_review_table,
    split,
)


def minimal_pipeline() -> Pipeline:
    """数値 4 列だけを扱う最小の Pipeline（前処理 2 段 + モデル 1 段）。"""
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        ]
    )


def basics(df) -> dict[str, object]:
    """最小の Pipeline と、列ごとに前処理を振り分けた Pipeline の形を並べて調べる。"""
    X, y = features_target(df)
    X_train, X_test, y_train, y_test = split(X, y)

    # ① 数値 4 列だけ。fit は 1 回で 3 段すべてに伝わる
    small = minimal_pipeline().fit(X_train[NUMERIC], y_train)
    proba_shape = small.predict_proba(X_test[NUMERIC]).shape

    # ② 数値 4 列 + カテゴリ 3 列。ColumnTransformer が列ごとに前処理を振り分ける
    full = build_pipeline().fit(X_train, y_train)
    pre = full.named_steps["pre"]
    transformed = pre.transform(X_train)
    names = [str(name) for name in pre.get_feature_names_out()]

    return {
        "n_rows": len(df),
        "n_train": len(X_train),
        "n_test": len(X_test),
        "region_missing": int(df["region"].isna().sum()),
        "region_missing_rate": float(df["region"].isna().mean()),
        "small_steps": list(minimal_pipeline().named_steps),
        "full_steps": list(full.named_steps),
        "proba_shape": proba_shape,
        "n_input": int(X_train.shape[1]),
        "n_output": int(transformed.shape[1]),
        "levels": {column: int(df[column].nunique()) for column in CATEGORICAL},
        "names": names,
        "auc": auc_of(full, X_test, y_test),
    }


def main() -> None:
    result = basics(load_review_table())

    print("■ 1. 使うデータ")
    print(f"レビュー件数            : {result['n_rows']:,} 件")
    print(f"訓練データ / 評価データ : {result['n_train']:,} 件 / {result['n_test']:,} 件")
    print(
        f"region の欠損           : {result['region_missing']:,} 件"
        f"（{result['region_missing_rate'] * 100:.2f}%）"
    )
    print()

    print("■ 2. 数値 4 列だけの最小の Pipeline")
    print(f"ステップの名前          : {result['small_steps']}")
    print(f"predict_proba の形      : {result['proba_shape']}")
    print()

    print("■ 3. 列ごとに前処理を振り分けた Pipeline")
    print(f"ステップの名前          : {result['full_steps']}")
    print(f"入力の列数              : {result['n_input']} 列")
    print(f"変換後の列数            : {result['n_output']} 列")
    for column, levels in result["levels"].items():
        print(f"  {column:<9} の水準の数 : {levels}")
    print(f"テストデータの ROC AUC  : {result['auc']:.4f}")


if __name__ == "__main__":
    main()
