"""問題2 の解答: 変換後の 20 列に名前を付けてたどる。

実行:
    docker compose exec lab python src/session25/q2_feature_names.py
"""

from __future__ import annotations

import pandas as pd

from common import (
    CATEGORICAL,
    build_pipeline,
    features_target,
    load_review_table,
    split,
)


def analyze(df) -> dict[str, object]:
    """列名を取り出し、接頭辞ごとの内訳と係数の並びを突き合わせる。"""
    X, y = features_target(df)
    X_train, X_test, y_train, y_test = split(X, y)
    pipeline = build_pipeline().fit(X_train, y_train)

    pre = pipeline.named_steps["pre"]
    model = pipeline.named_steps["model"]
    names = [str(name) for name in pre.get_feature_names_out()]

    encoder = pre.named_transformers_["cat"].named_steps["onehot"]
    n_levels = {column: len(values) for column, values in zip(CATEGORICAL, encoder.categories_)}

    # 列名と係数を 1 つの表にする（次章でこの表を「解釈」に使う）
    table = pd.DataFrame({"feature": names, "coef": model.coef_[0]})

    return {
        "names": names,
        "n_names": len(names),
        "n_numeric": sum(1 for name in names if name.startswith("num__")),
        "n_onehot": sum(1 for name in names if name.startswith("cat__")),
        "per_column": {
            column: sum(1 for name in names if name.startswith(f"cat__{column}_"))
            for column in CATEGORICAL
        },
        "n_levels": n_levels,
        "levels_sum": sum(n_levels.values()),
        "coef_shape": model.coef_.shape,
        "table_rows": len(table),
        "names_match_coef": len(names) == model.coef_.shape[1],
    }


def main() -> None:
    result = analyze(load_review_table())

    print("■ 変換後の列名")
    for start in range(0, result["n_names"], 4):
        print("  " + "  ".join(result["names"][start : start + 4]))
    print()

    print("■ 内訳")
    print(f"列の合計         : {result['n_names']} 列")
    print(f"num__ で始まる列 : {result['n_numeric']} 列")
    print(f"cat__ で始まる列 : {result['n_onehot']} 列")
    for column, count in result["per_column"].items():
        print(f"  cat__{column}_* : {count} 列（水準の数 {result['n_levels'][column]}）")
    print(f"水準の数の合計   : {result['levels_sum']}")
    print()

    print("■ 係数との対応")
    print(f"coef_ の形           : {result['coef_shape']}")
    print(f"列名と係数の表の行数 : {result['table_rows']} 行")
    print(f"列名の数と係数の数が一致 : {result['names_match_coef']}")


if __name__ == "__main__":
    main()
