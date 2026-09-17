"""訓練・検証・テストの 3 分割と、本書で使う 2 分割の関係を確かめる。

使い方:
    docker compose exec lab python src/session15/split_roles.py
"""

from __future__ import annotations

from common import (
    FEATURES,
    RANDOM_STATE,
    TARGET,
    TEST_SIZE,
    VALID_SIZE,
    load_review_features,
    split_features,
    split_three_way,
)


def main() -> None:
    df = load_review_features()
    X_train, X_test, y_train, y_test = split_features(df)
    (X_fit, y_fit), (X_valid, y_valid), (X_test3, y_test3) = split_three_way(df)

    print("■ 高評価レビューの分類（星 4 以上を 1 とする二値分類）")
    print(f"母集団 : {len(df):,} 件（rating の欠損を落とした行）")
    print(f"特徴量 : {' / '.join(FEATURES)}")
    print(f"正例率（全体） : {df[TARGET].mean():.4f}")
    print()

    print(f"■ 訓練と評価の 2 分割（test_size={TEST_SIZE} / random_state={RANDOM_STATE} / stratify=y）")
    print(f"訓練データ : {len(X_train):>6,} 件 / 正例率 {y_train.mean():.4f}")
    print(f"評価データ : {len(X_test):>6,} 件 / 正例率 {y_test.mean():.4f}")
    print(f"2 つの合計が母集団と一致するか : {len(X_train) + len(X_test) == len(df)}")
    # 同じ行が両方に入っていないこと（入っていたら評価がまったく信用できない）
    overlap = set(X_train.index) & set(X_test.index)
    print(f"同じ行が両方に入っていないか : {len(overlap) == 0}")
    print()

    print(f"■ 訓練データをさらに分けた 3 分割（検証データに {VALID_SIZE:.0%} を回す）")
    print(f"学習用       : {len(X_fit):>6,} 件 / 正例率 {y_fit.mean():.4f}")
    print(f"検証データ   : {len(X_valid):>6,} 件 / 正例率 {y_valid.mean():.4f}")
    print(f"テストデータ : {len(X_test3):>6,} 件 / 正例率 {y_test3.mean():.4f}")
    total = len(X_fit) + len(X_valid) + len(X_test3)
    print(f"3 つの合計が母集団と一致するか : {total == len(df)}")
    # テストは最初に取り分けて、あとの分け方を変えても触らない
    same_test = X_test.index.equals(X_test3.index)
    print(f"テストデータは 2 分割のときと同じ行か : {same_test}")
    print()

    print("■ それぞれの役割")
    print("学習用       : fit してモデルのパラメータを決める")
    print("検証データ   : 設定（木の深さなど）を選ぶ・モデルを比べる。何度でも見てよい")
    print("テストデータ : 最後に 1 回だけ使う。設計の判断に使った瞬間、テストではなくなる")


if __name__ == "__main__":
    main()
