"""問題2 の解答: region と channel を One-Hot にする（訓練で fit、評価は transform だけ）。

使い方:
    docker compose exec lab python src/session13/q2_onehot_encoder.py
"""

from __future__ import annotations

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder

from common import MISSING_LABEL, RANDOM_STATE, TEST_SIZE, load_customers

COLUMNS = ["region", "channel"]


def main() -> None:
    customers = load_customers()
    filled = customers.copy()
    # 欠損を「不明」という 1 つの水準にする。埋めないと列名が機械的なものになる
    filled["region"] = filled["region"].fillna(MISSING_LABEL)

    train, test = train_test_split(filled[COLUMNS], test_size=TEST_SIZE, random_state=RANDOM_STATE)
    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    encoder.set_output(transform="pandas").fit(train)  # fit は訓練データだけ
    encoded_train = encoder.transform(train)
    encoded_test = encoder.transform(test)  # 評価データは transform だけ

    print("■ 訓練データで fit して、評価データは transform だけ")
    print(f"訓練 {len(train):,} 行 / 評価 {len(test):,} 行")
    print(f"覚えた水準 : region {len(encoder.categories_[0])} / channel {len(encoder.categories_[1])}")
    print(f"出力の列数 : 訓練 {encoded_train.shape[1]} 列 / 評価 {encoded_test.shape[1]} 列")
    increased = encoded_train.shape[1] - len(COLUMNS)
    print(f"入力 {len(COLUMNS)} 列 → 出力 {encoded_train.shape[1]} 列（増えた列は {increased}）")
    print()

    print("■ できた列の名前")
    print(" / ".join(encoded_train.columns))
    print()

    print("■ 1 行に立つ 1 の数は、必ず入力の列数と同じになる")
    print(f"訓練 : {bool((encoded_train.sum(axis=1) == len(COLUMNS)).all())}")
    print(f"評価 : {bool((encoded_test.sum(axis=1) == len(COLUMNS)).all())}")
    filled_count = int(filled["region"].eq(MISSING_LABEL).sum())
    print(f"「{MISSING_LABEL}」に置き換えた行数（全 {len(filled):,} 行のうち） : {filled_count}")


if __name__ == "__main__":
    main()
