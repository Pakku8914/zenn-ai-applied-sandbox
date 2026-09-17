"""早期終了（early stopping）で「止め時」をモデル自身に決めさせる。

LightGBM 4.7.0 では fit(..., eval_set=[(X, y)]) が非推奨です。
本書のコードは eval_X / eval_y で書き、非推奨の書き方で出る警告も最後に実演します。

使い方:
    docker compose exec lab python src/session19/early_stopping.py
"""

from __future__ import annotations

import warnings

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")  # 画面のない環境なのでファイルに保存する
import matplotlib.pyplot as plt

from common import (
    EARLY_STOPPING_ROUNDS,
    MANY_ESTIMATORS,
    OUT_DIR,
    SLOW_LEARNING_RATE,
    load_review_table,
    logloss_curve,
    make_lgbm,
    prepare,
    scores_from_proba,
    split_xy,
)


def fit_with_early_stopping(train, y_train, valid, y_valid):
    """上限 1000 本で学習を始め、検証データが 50 回続けて改善しなければ打ち切る。"""
    model = make_lgbm(n_estimators=MANY_ESTIMATORS, learning_rate=SLOW_LEARNING_RATE)
    model.fit(
        train,
        y_train,
        # LightGBM 4.7.0 では eval_set ではなく eval_X / eval_y を使う
        eval_X=valid,
        eval_y=y_valid,
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )
    return model


def deprecated_eval_set(train, y_train, valid, y_valid) -> list[tuple[str, str]]:
    """古い書き方（eval_set）で出る警告を捕まえて、型名と文面を返す。

    警告を warnings.filterwarnings("ignore") で消してはいけません。
    「動くけれど将来消える書き方」を知らせてくれている大事な出力です。
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        make_lgbm(n_estimators=10).fit(train, y_train, eval_set=[(valid, y_valid)])
    return [(type(item.message).__name__, str(item.message)) for item in caught]


def draw(path, counts, train_loss, valid_loss, best_iteration: int) -> None:
    """木の本数に対する対数損失を訓練・検証の 2 本で描き、止まった位置に線を引く。"""
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.plot(counts, train_loss, color="#4c78a8", linewidth=2, label="訓練データ")
    ax.plot(counts, valid_loss, color="#e45756", linewidth=2, label="検証データ")
    ax.axvline(best_iteration, color="#54a24b", linestyle="--", linewidth=1.5)
    ax.text(best_iteration + 2, max(valid_loss), f"best_iteration = {best_iteration}", color="#54a24b")
    ax.set_xlabel("木の本数")
    ax.set_ylabel("対数損失（小さいほど良い）")
    ax.set_title("訓練は下がり続けるのに、検証は途中から上向く")
    ax.grid(alpha=0.3)
    ax.legend(loc="center right")
    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)

    # この章では簡単さのために評価データを検証にも使います（本当は分けるべき。セッション22 で扱います）
    model = fit_with_early_stopping(train, y_train, test, y_test)
    scores = scores_from_proba(y_test, model.predict_proba(test)[:, 1])

    print("■ 早期終了の結果（上限 1000 本・learning_rate 0.05・50 回改善しなければ打ち切り）")
    print(f"best_iteration_: {model.best_iteration_}")
    print(f"実際に建てた木の本数: {model.booster_.num_trees()}（打ち切り判定のぶんだけ余分に建つ）")
    print(f"best_iteration_ の時点での検証データの ROC AUC: {scores['roc_auc']:.4f}")
    print(f"上限の 1000 本まで使ったか: {model.best_iteration_ >= 1000}")
    print()

    counts, train_loss, valid_loss = logloss_curve(model, train, y_train, test, y_test)
    print("■ 対数損失の動き（抜粋）")
    print(f"最初（{counts[0]} 本）  : 訓練 {train_loss[0]:.4f} / 検証 {valid_loss[0]:.4f}")
    print(f"最後（{counts[-1]} 本）: 訓練 {train_loss[-1]:.4f} / 検証 {valid_loss[-1]:.4f}")
    print(f"訓練の対数損失は下がり続けたか: {train_loss[-1] < train_loss[0]}")
    print(f"検証の対数損失は途中で底を打ったか: {min(valid_loss) < valid_loss[-1]}")
    print()

    print("■ 古い書き方（eval_set）を使うと出る警告")
    for name, message in deprecated_eval_set(train, y_train, test, y_test):
        if "eval_set" in message:
            print(f"{name}: {message}")
    print()
    print("判断: 木の本数は人が当てるものではなく、検証データに決めてもらえます。")

    path = OUT_DIR / "s19_learning_curve.png"
    draw(path, counts, train_loss, valid_loss, model.best_iteration_)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
