"""問題5 の解答: カテゴリを category 型のまま渡す版と One-Hot 版を比べ、注意点も確かめる。

使い方:
    docker compose exec lab python src/session19/q5_native_categorical.py
"""

from __future__ import annotations

import pandas as pd

from common import (
    fit_and_score,
    load_review_table,
    make_lgbm,
    native_frames,
    prepare,
    print_scores,
    split_xy,
)

# 訓練データには無いカテゴリ（セッション13 で OneHotEncoder が ValueError を出した例と同じ）
UNKNOWN_CATEGORY = "写真集"


def compare(df) -> dict[str, dict[str, float]]:
    """One-Hot 版と category 型版を同じ分割・同じパラメータで比べる。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    _, onehot = fit_and_score(make_lgbm(), train, y_train, test, y_test)

    train_native, test_native = native_frames(X_train, X_test)
    model, native = fit_and_score(make_lgbm(), train_native, y_train, test_native, y_test)
    return {
        "One-Hot（9 列）": onehot,
        "category 型（5 列）": native,
        "_model": model,
        "_columns": {"onehot": train.shape[1], "native": train_native.shape[1]},
    }


def unknown_level(df) -> dict[str, object]:
    """訓練データに無いカテゴリが来たときに何が起きるかを確かめる。"""
    X_train, X_test, y_train, y_test = split_xy(df)
    train_native, test_native = native_frames(X_train, X_test)
    model = make_lgbm().fit(train_native, y_train)

    row = test_native.head(1).copy()
    # 水準を訓練データから決めているので、知らないカテゴリは欠損（NaN）になる
    row["category"] = pd.Series([UNKNOWN_CATEGORY], index=row.index).astype(row["category"].dtype)
    proba = model.predict_proba(row)[:, 1]
    return {
        "categories": list(train_native["category"].cat.categories),
        "became_nan": bool(row["category"].isna().iloc[0]),
        "predicted": bool(len(proba) == 1),
    }


def main() -> None:
    df = load_review_table()
    result = compare(df)

    print("■ カテゴリの渡し方を変えて比べる（LightGBM・既定 200 本）")
    for label in ["One-Hot（9 列）", "category 型（5 列）"]:
        print_scores(label, result[label])
    print(f"モデルが受け取った列の数: One-Hot {result['_columns']['onehot']} 列 / category 型 {result['_columns']['native']} 列")
    print(f"どちらが良かったか: {'category 型' if result['category 型（5 列）']['roc_auc'] > result['One-Hot（9 列）']['roc_auc'] else 'One-Hot'}")
    print()

    info = unknown_level(df)
    print("■ 知らないカテゴリが来たとき")
    print(f"訓練データから決めた水準: {info['categories']}")
    print(f"『{UNKNOWN_CATEGORY}』は欠損（NaN）になったか: {info['became_nan']}")
    print(f"それでも予測はできたか: {info['predicted']}")
    print()
    print("説明: category 型のまま渡すと、LightGBM は『この水準の集合 対 残り』という分け方を直接試せます。")
    print("      列が増えないぶん 1 本の木で複数の水準をまとめて扱えるのが利点です。")
    print("      注意点は 3 つあります。")
    print("      ① 水準の並びを訓練データから決め、評価データにも同じものを適用する（別々に astype しない）")
    print("      ② 知らない水準は欠損として扱われる。OneHotEncoder(handle_unknown='ignore') は全部 0 にする")
    print("      ③ 文字列のまま渡すと例外で止まる。必ず astype('category') を通す")
    print("      そして『どちらが良いか』はデータ次第です。数値が近いときは、説明しやすい方を選びます。")


if __name__ == "__main__":
    main()
