"""水準の多い列（book_id・600 水準）を One-Hot にしたときの列数と、その対処を確かめる。

使い方:
    docker compose exec lab python src/session13/high_cardinality.py
"""

from __future__ import annotations

from sklearn.preprocessing import OneHotEncoder

from common import ID_FEATURE, load_review_features, split_features

MAX_CATEGORIES = 20  # 出力する列数の上限（まとめ用の 1 列を含む）


def main() -> None:
    X_train, _, _, _ = split_features(load_review_features())

    plain = OneHotEncoder(sparse_output=False, handle_unknown="ignore").fit(X_train[[ID_FEATURE]])
    wide = plain.transform(X_train[[ID_FEATURE]])
    print("■ book_id をそのまま One-Hot にする")
    print(f"入力 : 1 列（book_id）/ 水準の数 {len(plain.categories_[0])}")
    print(f"出力 : {wide.shape[1]} 列（表の大きさは {wide.shape[0]:,} 行 × {wide.shape[1]} 列）")
    print(f"1 行あたりに立つ 1 の数 : {int(wide[0].sum())}（残りの {wide.shape[1] - 1} 列は 0）")
    print()

    grouped = OneHotEncoder(
        sparse_output=False,
        handle_unknown="infrequent_if_exist",  # 未知の水準は「まとめ用の列」に入れる
        max_categories=MAX_CATEGORIES,
    ).fit(X_train[[ID_FEATURE]])
    narrow = grouped.transform(X_train[[ID_FEATURE]])
    print(f"■ 出現の少ない水準をまとめる（max_categories={MAX_CATEGORIES}）")
    print(f"出力 : {narrow.shape[1]} 列（よく出る {MAX_CATEGORIES - 1} 水準 + まとめ用の 1 列）")
    print(f"まとめられた水準の数 : {len(grouped.infrequent_categories_[0])}")
    print(f"まとめ用の列の名前   : {grouped.get_feature_names_out([ID_FEATURE])[-1]}")
    print(f"すべての行で 1 の合計が 1 になるか : {bool((narrow.sum(axis=1) == 1).all())}")


if __name__ == "__main__":
    main()
