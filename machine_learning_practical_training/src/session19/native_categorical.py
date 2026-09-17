"""カテゴリ変数を One-Hot に開かず、pandas の category 型のまま LightGBM に渡す。

使い方:
    docker compose exec lab python src/session19/native_categorical.py
"""

from __future__ import annotations

from common import (
    CATEGORICAL,
    fit_and_score,
    load_review_table,
    make_lgbm,
    native_frames,
    prepare,
    print_scores,
    split_xy,
)


def try_raw_strings(X_train, y_train):
    """文字列のまま（category 型にせず）渡すとどうなるかを確かめる。

    例外の型名だけを返します（メッセージの文面はバージョンで変わるため頼りにしません）。
    """
    try:
        make_lgbm(n_estimators=10).fit(X_train, y_train)
    except Exception as error:  # noqa: BLE001 — 型名を見せることが目的
        return type(error).__name__
    return "例外は出ませんでした"


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)

    # ① これまでどおり One-Hot に開く（数値 4 列 + カテゴリ 5 列 = 9 列）
    pre, train, test, names = prepare(X_train, X_test)
    _, onehot_scores = fit_and_score(make_lgbm(), train, y_train, test, y_test)

    # ② category 型のまま渡す（5 列に開かず 1 列のまま）
    train_native, test_native = native_frames(X_train, X_test)
    native_model, native_scores = fit_and_score(make_lgbm(), train_native, y_train, test_native, y_test)

    print("■ 同じ LightGBM・同じ分割で、カテゴリの渡し方だけを変える")
    print(f"① One-Hot（{train.shape[1]} 列）")
    print_scores("   LightGBM（既定 200 本）", onehot_scores)
    print(f"② category 型のまま（{train_native.shape[1]} 列）")
    print_scores("   LightGBM（既定 200 本）", native_scores)
    print()

    print("■ モデルが受け取った列")
    print(f"One-Hot 版の列名: {names}")
    print(f"category 型版の列名: {list(native_model.feature_name_)}")
    print(f"{CATEGORICAL[0]} 列の dtype: {train_native['category'].dtype}")
    print(f"水準（訓練データから決めた並び）: {list(train_native['category'].cat.categories)}")
    print()

    print("■ 文字列のまま渡すと止まる")
    print(f"例外の型: {try_raw_strings(X_train, y_train)}")
    print()
    print("判断: 列が 9 列から 5 列に減り、コードも短くなります。ただし『同じ数値でも別のモデル』です。")
    print("      どちらが良いかは実行して比べ、理由を説明できる方を選びます。")


if __name__ == "__main__":
    main()
