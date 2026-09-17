"""問題4 の解答: One-Hot と Label を、線形モデルと木モデルの両方で比べる。

使い方:
    docker compose exec lab python src/session13/q4_encoding_models.py
"""

from __future__ import annotations

import lightgbm
from sklearn.linear_model import LogisticRegression

from common import CATEGORY_FEATURE, RANDOM_STATE, auc_of, design, load_review_features
from common import onehot_features, ordinal_features, scaled_numeric, split_features

LR_GAP = 0.05  # 線形モデルは「はっきり下がる」ことを確かめるための線
GBM_GAP = 0.005  # 木モデルは「本書の許容誤差の中に収まる」ことを確かめるための線


def main() -> None:
    df = load_review_features()
    X_train, X_test, y_train, y_test = split_features(df)
    num_train, num_test = scaled_numeric(X_train, X_test)
    oh_train, oh_test, _ = onehot_features(X_train, X_test)
    od_train, od_test, od_encoder = ordinal_features(X_train, X_test)

    print("■ 高評価レビュー（星 4 以上）の分類")
    print(f"訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件 / 正例率 {df['is_high'].mean():.4f}")
    print()

    scores: dict[tuple[str, str], float] = {}
    print("■ カテゴリの変換だけを入れ替えた ROC AUC")
    print("変換    | 列数 | ロジスティック回帰 | LightGBM")
    for label, cat_train, cat_test in [("One-Hot", oh_train, oh_test), ("Label", od_train, od_test)]:
        train, test = design(num_train, cat_train), design(num_test, cat_test)
        scores[(label, "lr")] = auc_of(
            LogisticRegression(max_iter=1000, random_state=RANDOM_STATE), train, y_train, test, y_test
        )
        scores[(label, "gbm")] = auc_of(
            lightgbm.LGBMClassifier(n_estimators=200, random_state=RANDOM_STATE, verbose=-1),
            train,
            y_train,
            test,
            y_test,
        )
        print(
            f"{label:<7} | {train.shape[1]:>4} | "
            f"{scores[(label, 'lr')]:>18.4f} | {scores[(label, 'gbm')]:>8.4f}"
        )
    print()

    drop_lr = scores[("One-Hot", "lr")] - scores[("Label", "lr")]
    drop_gbm = scores[("One-Hot", "gbm")] - scores[("Label", "gbm")]
    print("■ Label に変えたときの落ち込み")
    print(f"ロジスティック回帰 : {LR_GAP} より大きく下がったか {bool(drop_lr > LR_GAP)}")
    print(f"LightGBM           : {GBM_GAP} より大きく下がったか {bool(drop_gbm > GBM_GAP)}")
    print()

    rates = y_train.groupby(X_train[CATEGORY_FEATURE]).mean()
    in_code_order = rates.reindex(od_encoder.categories_[0])
    print("■ 訓練データのカテゴリ別 高評価率（番号の順に並べる）")
    for code, (name, rate) in enumerate(in_code_order.items()):
        print(f"{name}({code}) : {rate:.4f}")
    print(f"番号の順に単調に増えるか : {bool(in_code_order.is_monotonic_increasing)}")
    print(f"番号の順に単調に減るか   : {bool(in_code_order.is_monotonic_decreasing)}")
    print()

    print("■ 結論")
    print("Label は 5 つの水準を 1 本の数直線に並べる変換です。番号の順に高評価率が上下しているので、")
    print("係数 1 つで表すロジスティック回帰はこの関係を表現できず、AUC が大きく下がりました。")
    print("木モデルは「番号が 2.5 より大きいか」のような分岐を何度も作れるため、ほとんど影響を受けません。")


if __name__ == "__main__":
    main()
