"""スケーリングは「訓練データで fit、検証データは transform だけ」であることを確かめる。

使い方:
    docker compose exec lab python src/session12/fit_transform_order.py
"""

from __future__ import annotations

import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from common import RANDOM_STATE, TEST_SIZE, load_review_features, make_design_matrix


def shown(values: np.ndarray) -> list[float]:
    """表示用に小数 4 桁へ丸めた list にする（numpy の表記をそのまま出さないため）。"""
    return [round(float(v), 4) for v in np.ravel(values)]


def main() -> None:
    # 手で検算できる 4 つの値だけで、順序の違いを確かめる
    train = np.array([[100.0], [200.0], [300.0]])
    test = np.array([[400.0]])

    print("■ おもちゃのデータで手順の違いを確かめる")
    print(f"訓練データ : {shown(train)}")
    print(f"検証データ : {shown(test)}")
    print()

    scaler = StandardScaler().fit(train)  # fit は訓練データだけに対して行う
    print("正しい手順（訓練で fit → 検証は transform だけ）")
    print(f"  訓練データの平均 {scaler.mean_[0]:.4f} / 標準偏差 {scaler.scale_[0]:.4f}")
    print(f"  変換後の訓練データ : {shown(scaler.transform(train))}")
    print(f"  変換後の検証データ : {shown(scaler.transform(test))}")

    print("間違った手順（検証データにも fit_transform してしまう）")
    print(f"  変換後の検証データ : {shown(StandardScaler().fit_transform(test))}")
    print("  → 400 という同じ値が、手順によって別の数値に変わってしまう")
    print()

    minmax = MinMaxScaler().fit(train)
    print("MinMaxScaler で同じことをすると")
    print(f"  変換後の訓練データ : {shown(minmax.transform(train))}")
    print(f"  変換後の検証データ : {shown(minmax.transform(test))}")
    print("  → 0〜1 に収まるのは訓練データだけ。範囲外の値は 1 を超える")
    print()

    # 実データでも同じことを確認する（unit_price 1 列だけを取り出して見る）
    df = load_review_features()
    X, y = make_design_matrix(df), df["is_high"]
    X_train, X_test, _, _ = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    price_train = X_train[["unit_price"]]
    price_test = X_test[["unit_price"]]

    fit_on_train = StandardScaler().fit(price_train)
    fit_on_all = StandardScaler().fit(X[["unit_price"]])
    correct = fit_on_train.transform(price_test)
    leaked = StandardScaler().fit_transform(price_test)

    print("■ 実データ（unit_price）で確かめる")
    print(f"訓練で fit した平均と全データで fit した平均が一致するか : "
          f"{bool(fit_on_train.mean_[0] == fit_on_all.mean_[0])}")
    print(f"正しい手順で変換した検証データの平均がほぼ 0 か : {bool(np.isclose(correct.mean(), 0.0))}")
    print(f"検証データに fit_transform した場合の平均がほぼ 0 か : {bool(np.isclose(leaked.mean(), 0.0))}")
    print("→ 検証データの平均がちょうど 0 になっていたら、検証データを見て fit している証拠です")


if __name__ == "__main__":
    main()
