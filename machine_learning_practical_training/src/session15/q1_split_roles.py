"""問題1 の解答：2 分割と 3 分割を自分で作り、それぞれの役割を言葉にする。

使い方:
    docker compose exec lab python src/session15/q1_split_roles.py
"""

from __future__ import annotations

import pandas as pd
from sklearn.model_selection import train_test_split

from common import FEATURES, RANDOM_STATE, TARGET, TEST_SIZE, VALID_SIZE, load_review_features

# どの作業にどのデータを使うか（この割り当てを崩すと評価が信用できなくなる）
ROLES = [
    ("モデルのパラメータを決める（fit）", "学習用"),
    ("木の深さなどの設定を選ぶ", "検証データ"),
    ("2 つのモデルのどちらが良いかを決める", "検証データ"),
    ("特徴量を足すかどうかを決める", "検証データ"),
    ("最終的な性能を報告する", "テストデータ（1 回だけ）"),
]


def make_splits(df: pd.DataFrame) -> dict[str, tuple[pd.DataFrame, pd.Series]]:
    """2 分割を作り、その訓練データをさらに分けて 3 分割にする。"""
    X, y = df[FEATURES], df[TARGET]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    # テストは先に取り分ける。以降どう分け直してもテストには触らない
    X_fit, X_valid, y_fit, y_valid = train_test_split(
        X_train, y_train, test_size=VALID_SIZE, random_state=RANDOM_STATE, stratify=y_train
    )
    return {
        "全体": (X, y),
        "訓練": (X_train, y_train),
        "評価": (X_test, y_test),
        "学習用": (X_fit, y_fit),
        "検証": (X_valid, y_valid),
    }


def main() -> None:
    df = load_review_features()
    parts = make_splits(df)

    print("■ 母集団と 2 分割")
    for name in ("全体", "訓練", "評価"):
        X, y = parts[name]
        print(f"{name} : {len(X):>6,} 件 / 正例率 {y.mean():.4f}")
    train_n, test_n = len(parts["訓練"][0]), len(parts["評価"][0])
    print(f"訓練 + 評価 が母集団と一致するか : {train_n + test_n == len(df)}")
    overlap = set(parts["訓練"][0].index) & set(parts["評価"][0].index)
    print(f"同じ行が訓練と評価の両方に入っていないか : {len(overlap) == 0}")
    # 層化分割なので、訓練と評価の正例率は 0.001 も離れない
    rate_gap = abs(float(parts["訓練"][1].mean()) - float(parts["評価"][1].mean()))
    print(f"訓練と評価の正例率の差が 0.001 未満か : {rate_gap < 0.001}")
    print()

    print(f"■ 訓練データをさらに分けた 3 分割（検証データに {VALID_SIZE:.0%}）")
    for name in ("学習用", "検証", "評価"):
        X, y = parts[name]
        print(f"{name} : {len(X):>6,} 件 / 正例率 {y.mean():.4f}")
    three = sum(len(parts[name][0]) for name in ("学習用", "検証", "評価"))
    print(f"3 つの合計が母集団と一致するか : {three == len(df)}")
    print(f"学習用 + 検証 が訓練データと一致するか : "
          f"{len(parts['学習用'][0]) + len(parts['検証'][0]) == train_n}")
    print()

    print("■ どの作業にどのデータを使うか")
    for task, data in ROLES:
        print(f"{task} → {data}")
    print()

    print("■ テストデータを設計の判断に使ってはいけない理由")
    print("何度も見て良いほうを選ぶと、テストデータに合わせてモデルを選んだことになり、")
    print("未知のデータに対する性能（汎化性能）を過大に見積もってしまうからです。")


if __name__ == "__main__":
    main()
