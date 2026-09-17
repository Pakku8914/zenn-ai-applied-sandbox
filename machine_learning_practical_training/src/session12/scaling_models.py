"""スケーリングの有無・種類ごとに、線形モデルと木モデルの ROC AUC を測る。

使い方:
    docker compose exec lab python src/session12/scaling_models.py
"""

from __future__ import annotations

import lightgbm
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from common import (
    NUMERIC_FEATURES,
    OUT_DIR,
    RANDOM_STATE,
    TEST_SIZE,
    load_review_features,
    make_design_matrix,
    scale_numeric,
)

SCALERS = [("none", "スケーリングなし"), ("standard", "StandardScaler  "), ("minmax", "MinMaxScaler    ")]


def auc_of(model, X_train, y_train, X_test, y_test) -> float:
    """モデルを訓練データで学習し、評価データの ROC AUC を返す。"""
    model.fit(X_train, y_train)
    return float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))


def main() -> None:
    df = load_review_features()
    X, y = make_design_matrix(df), df["is_high"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    print("■ 高評価レビュー（星 4 以上）の分類でスケーリングの効果を測る")
    print(f"特徴量 {X.shape[1]} 列 / 訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件 / 正例率 {y.mean():.4f}")
    print()

    print("スケーリング    | ロジスティック回帰 | LightGBM")
    scaled_sets = {}
    for name, label in SCALERS:
        train, test = scale_numeric(X_train, X_test, name)
        scaled_sets[name] = (train, test)
        # ロジスティック回帰は lbfgs では random_state を使わないが、本書の習慣として明示する
        auc_lr = auc_of(LogisticRegression(max_iter=1000, random_state=RANDOM_STATE), train, y_train, test, y_test)
        auc_gbm = auc_of(
            lightgbm.LGBMClassifier(n_estimators=200, random_state=RANDOM_STATE, verbose=-1),
            train,
            y_train,
            test,
            y_test,
        )
        print(f"{label} | {auc_lr:.4f}            | {auc_gbm:.4f}")
    print()

    print("■ 変換後の数値はどうなっているか（unit_price の訓練データ）")
    standard_train = scaled_sets["standard"][0]["unit_price"]
    minmax_train = scaled_sets["minmax"][0]["unit_price"]
    print(f"StandardScaler : 平均が 0 か {bool(np.isclose(standard_train.mean(), 0.0))}"
          f" / 標準偏差が 1 か {bool(np.isclose(standard_train.std(ddof=0), 1.0))}")
    print(f"MinMaxScaler   : 最小 {minmax_train.min():.4f} / 最大 {minmax_train.max():.4f}")
    standard_test = scaled_sets["standard"][1]["unit_price"]
    print(f"検証データの平均がちょうど 0 か : {bool(standard_test.mean() == 0.0)}")
    print()

    # 3 通りの unit_price をヒストグラムで並べる。目盛だけが変わり、形は変わらない
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.4))
    panels = [
        ("素のまま（円）", X_train["unit_price"]),
        ("StandardScaler 後", standard_train),
        ("MinMaxScaler 後", minmax_train),
    ]
    for ax, (title, values) in zip(axes, panels):
        ax.hist(values, bins=40, color="#4c78a8")
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("値")
        ax.set_ylabel("件数")
    fig.suptitle("スケーリングは目盛を変えるだけで、分布の形は変えない", fontsize=13)
    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(OUT_DIR / "s12_scaling_effect.png", dpi=100)
    plt.close(fig)
    print("図を保存しました: outputs/s12_scaling_effect.png")


if __name__ == "__main__":
    main()
