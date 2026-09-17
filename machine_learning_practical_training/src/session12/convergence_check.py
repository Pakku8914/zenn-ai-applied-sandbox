"""スケーリングが「精度」ではなく「収束」に効くことを確かめる。

scikit-learn の LogisticRegression は既定で max_iter=100 です。
スケーリングしていない特徴量を渡すと、この回数では計算が終わりません。

使い方:
    docker compose exec lab python src/session12/convergence_check.py
"""

from __future__ import annotations

import warnings

from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

from common import (
    RANDOM_STATE,
    TEST_SIZE,
    load_review_features,
    make_design_matrix,
    scale_numeric,
)

DEFAULT_MAX_ITER = 100  # scikit-learn の既定値


def fit_and_watch(X_train, y_train) -> tuple[bool, bool]:
    """既定の反復回数で学習し、(警告が出たか, 反復回数が上限に達したか) を返す。"""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")  # 警告を消すのではなく、受け取って中身を見る
        model = LogisticRegression(max_iter=DEFAULT_MAX_ITER, random_state=RANDOM_STATE)
        model.fit(X_train, y_train)
    warned = any(issubclass(w.category, ConvergenceWarning) for w in caught)
    return warned, int(model.n_iter_[0]) >= DEFAULT_MAX_ITER


def main() -> None:
    df = load_review_features()
    X, y = make_design_matrix(df), df["is_high"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )

    print(f"■ 既定の反復回数（max_iter={DEFAULT_MAX_ITER}）でロジスティック回帰は収束するか")
    print("スケーリング     | ConvergenceWarning | 反復回数が上限に達したか")
    for name, label in [("none", "スケーリングなし"), ("standard", "StandardScaler  ")]:
        train, _ = scale_numeric(X_train, X_test, name)
        warned, capped = fit_and_watch(train, y_train)
        print(f"{label} | {'出た' if warned else '出なかった'} | {capped}")

    print()
    print("警告の型名は ConvergenceWarning です（文面はバージョンで変わるため型で扱います）。")
    print("max_iter を増やせば警告は消えることもありますが、それは計算時間を足しただけです。")
    print("特徴量の目盛をそろえるほうが、根本的で速い対処になります。")


if __name__ == "__main__":
    main()
