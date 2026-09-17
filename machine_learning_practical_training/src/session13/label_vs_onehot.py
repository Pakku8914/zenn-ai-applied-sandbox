"""カテゴリの変換だけを入れ替えて、線形モデルと木モデルの ROC AUC を比べる。

使い方:
    docker compose exec lab python src/session13/label_vs_onehot.py
"""

from __future__ import annotations

import lightgbm
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression

from common import (
    CATEGORY_FEATURE,
    OUT_DIR,
    RANDOM_STATE,
    auc_of,
    design,
    load_review_features,
    onehot_features,
    ordinal_features,
    scaled_numeric,
    split_features,
)


def main() -> None:
    df = load_review_features()
    X_train, X_test, y_train, y_test = split_features(df)
    num_train, num_test = scaled_numeric(X_train, X_test)
    oh_train, oh_test, _ = onehot_features(X_train, X_test)
    od_train, od_test, od_encoder = ordinal_features(X_train, X_test)

    print("■ 高評価レビュー（星 4 以上）の分類 ― カテゴリの変換だけを入れ替える")
    print(f"訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件 / 正例率 {df['is_high'].mean():.4f}")
    print("数値 4 列（unit_price・pages・published_year・body_length）は前章と同じ標準化")
    print()

    print("変換    | 列数 | ロジスティック回帰 | LightGBM")
    for label, cat_train, cat_test in [
        ("One-Hot", oh_train, oh_test),
        ("Label", od_train, od_test),
    ]:
        train, test = design(num_train, cat_train), design(num_test, cat_test)
        auc_lr = auc_of(
            LogisticRegression(max_iter=1000, random_state=RANDOM_STATE), train, y_train, test, y_test
        )
        auc_gbm = auc_of(
            lightgbm.LGBMClassifier(n_estimators=200, random_state=RANDOM_STATE, verbose=-1),
            train,
            y_train,
            test,
            y_test,
        )
        print(f"{label:<7} | {train.shape[1]:>4} | {auc_lr:>18.4f} | {auc_gbm:>8.4f}")
    print()

    print("■ OrdinalEncoder が付けた番号（辞書順で 0 から）")
    print(" / ".join(f"{name}={code}" for code, name in enumerate(od_encoder.categories_[0])))
    print()

    rates = y_train.groupby(X_train[CATEGORY_FEATURE]).mean()
    print("■ 訓練データのカテゴリ別 高評価率（番号の順に並べる）")
    for name in od_encoder.categories_[0]:
        print(f"{name} : {rates[name]:.4f}")
    print()
    ordered = rates.sort_values(ascending=False)
    print("■ 高評価率の高い順に並べ替えると、番号の順とは一致しない")
    print(" > ".join(f"{name}({rate:.4f})" for name, rate in ordered.items()))

    # 図にすると「番号の順に並べても上下する」ことが一目で分かる
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    codes = list(range(len(od_encoder.categories_[0])))
    axes[0].plot(codes, [rates[name] for name in od_encoder.categories_[0]], marker="o", color="#e45756")
    axes[0].set_xticks(codes)
    axes[0].set_xticklabels([f"{name}\n({code})" for code, name in enumerate(od_encoder.categories_[0])])
    axes[0].set_title("番号の順に並べた高評価率")
    axes[0].set_xlabel("OrdinalEncoder が付けた番号")
    axes[0].set_ylabel("高評価率")
    axes[0].set_ylim(0.6, 1.0)
    axes[1].bar(codes, ordered.to_numpy(), color="#4c78a8")
    axes[1].set_xticks(codes)
    axes[1].set_xticklabels([str(name) for name in ordered.index])
    axes[1].set_title("高評価率の高い順に並べた場合")
    axes[1].set_ylabel("高評価率")
    axes[1].set_ylim(0.6, 1.0)
    fig.suptitle("辞書順の番号に意味はない ― この上下を 1 本の直線では表せない")
    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / "s13_category_rate.png", dpi=100)
    plt.close(fig)
    print()
    print("図を保存しました: outputs/s13_category_rate.png")


if __name__ == "__main__":
    main()
