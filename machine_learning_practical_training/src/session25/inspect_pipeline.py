"""組み立てた Pipeline の中身をたどる（本文 6 節）。

列名・水準・係数の並び・パラメータの差し替えを、Pipeline を分解せずに確認します。
ここで覚える `get_feature_names_out()` は、次章の「重要度の解釈」の入口になります。

実行:
    docker compose exec lab python src/session25/inspect_pipeline.py
"""

from __future__ import annotations

from common import (
    CATEGORICAL,
    build_pipeline,
    features_target,
    load_review_table,
    split,
)

NEW_C = 0.05  # set_params で差し替えるロジスティック回帰の C（正則化の強さ・セッション16）


def inspect(df) -> dict[str, object]:
    """学習済みの Pipeline から、列名・水準・係数・パラメータを取り出す。"""
    X, y = features_target(df)
    X_train, X_test, y_train, y_test = split(X, y)
    pipeline = build_pipeline().fit(X_train, y_train)

    pre = pipeline.named_steps["pre"]
    model = pipeline.named_steps["model"]
    names = [str(name) for name in pre.get_feature_names_out()]

    # ColumnTransformer の中の OneHotEncoder を名前でたどる
    encoder = pre.named_transformers_["cat"].named_steps["onehot"]
    levels = {
        column: [str(value) for value in values]
        for column, values in zip(CATEGORICAL, encoder.categories_)
    }

    # 前処理だけを取り出して使うこともできる（最後のステップを外したスライス）
    transformed = pipeline[:-1].transform(X_train)

    # モデルのパラメータだけを外から差し替える
    before = pipeline.get_params()["model__C"]
    pipeline.set_params(model__C=NEW_C)
    after = pipeline.get_params()["model__C"]
    refit = pipeline.fit(X_train, y_train)

    return {
        "names": names,
        "n_names": len(names),
        "n_numeric_names": sum(1 for name in names if name.startswith("num__")),
        "n_categorical_names": sum(1 for name in names if name.startswith("cat__")),
        "levels": levels,
        "n_levels": {column: len(values) for column, values in levels.items()},
        "coef_shape": model.coef_.shape,
        "names_match_coef": len(names) == model.coef_.shape[1],
        "transformed_shape": transformed.shape,
        "c_before": float(before),
        "c_after": float(after),
        "c_in_model": float(refit.named_steps["model"].C),
    }


def main() -> None:
    result = inspect(load_review_table())

    print("■ 1. 変換後の列名（get_feature_names_out）")
    for start in range(0, result["n_names"], 4):
        print("  " + "  ".join(result["names"][start : start + 4]))
    print()

    print("■ 2. 内訳")
    print(f"列の合計         : {result['n_names']} 列")
    print(f"num__ で始まる列 : {result['n_numeric_names']} 列")
    print(f"cat__ で始まる列 : {result['n_categorical_names']} 列")
    for column, count in result["n_levels"].items():
        print(f"  {column:<9} の水準 : {count} 個 -> {result['levels'][column]}")
    print()

    print("■ 3. 係数の並びは列名の並びと同じ")
    print(f"coef_ の形       : {result['coef_shape']}")
    print(f"列名の数と一致   : {result['names_match_coef']}")
    print(f"前処理だけの出力 : {result['transformed_shape']}")
    print()

    print("■ 4. パラメータの差し替え（set_params）")
    print(f"差し替え前の C   : {result['c_before']}")
    print(f"差し替え後の C   : {result['c_after']}")
    print(f"再学習したモデルの C : {result['c_in_model']}")


if __name__ == "__main__":
    main()
