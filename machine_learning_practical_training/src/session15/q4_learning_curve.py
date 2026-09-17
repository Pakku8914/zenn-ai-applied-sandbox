"""問題4 の解答：学習曲線を自分で計算し、2 パターンを読み分ける。

使い方:
    docker compose exec lab python src/session15/q4_learning_curve.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import learning_curve
from sklearn.tree import DecisionTreeClassifier

from common import (
    CV_FOLDS,
    FEATURES,
    MAX_ITER,
    OUT_DIR,
    RANDOM_STATE,
    TARGET,
    TRAIN_SIZES,
    load_review_features,
    pad,
    pipeline_for,
)

CLOSE_GAP = 0.01  # 2 本が「接近している」と判定する差
WIDE_GAP = 0.30  # 2 本が「開いたまま」と判定する差


def curve_of(model, X, y) -> tuple[list[int], list[float], list[float]]:
    """件数を変えながら 5 分割の交差検証を行い、訓練と検証の平均スコアを返す（自分で書く）。"""
    sizes, train_scores, valid_scores = learning_curve(
        pipeline_for(model),
        X,
        y,
        train_sizes=TRAIN_SIZES,
        cv=CV_FOLDS,
        scoring="roc_auc",
        random_state=RANDOM_STATE,  # shuffle は既定の False なので結果は毎回同じ
        n_jobs=1,
    )
    return (
        [int(n) for n in sizes],
        [float(v) for v in train_scores.mean(axis=1)],
        [float(v) for v in valid_scores.mean(axis=1)],
    )


def main() -> None:
    df = load_review_features()
    X, y = df[FEATURES], df[TARGET]

    curves = []
    for label, model in [
        ("ロジスティック回帰", LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        ("決定木（深さの制限なし）", DecisionTreeClassifier(random_state=RANDOM_STATE)),
    ]:
        sizes, train, valid = curve_of(model, X, y)
        curves.append({"label": label, "sizes": sizes, "train": train, "valid": valid})

    print(f"■ 学習曲線（train_sizes={TRAIN_SIZES} / cv={CV_FOLDS} / scoring=roc_auc）")
    print(f"学習に使った件数 : {' / '.join(f'{n:,}' for n in curves[0]['sizes'])}")
    print()
    for curve in curves:
        print(f"▼ {curve['label']}")
        print("件数    | 訓練 AUC | 検証 AUC")
        for n, t, v in zip(curve["sizes"], curve["train"], curve["valid"]):
            print(f"{n:<7,} | {t:>8.4f} | {v:>8.4f}")
        print()

    lr, tree = curves[0], curves[1]
    print("■ 判定")
    print(f"{pad(lr['label'])} : 末端の差が {CLOSE_GAP} 未満か : "
          f"{lr['train'][-1] - lr['valid'][-1] < CLOSE_GAP}")
    print(f"{pad(tree['label'])} : 末端の差が {WIDE_GAP} より大きいか : "
          f"{tree['train'][-1] - tree['valid'][-1] > WIDE_GAP}")
    print(f"決定木の検証 AUC がロジスティック回帰を一度も上回らないか : "
          f"{max(tree['valid']) < min(lr['valid'])}")
    # いちばん少ない件数といちばん多い件数（20 倍）の検証スコアを比べる
    growth = lr["valid"][-1] - lr["valid"][0]
    print(f"件数を 20 倍にしたときのロジスティック回帰の検証 AUC の伸びが {CLOSE_GAP} 未満か : "
          f"{growth < CLOSE_GAP}")
    print()

    print("■ 次の打ち手")
    print("ロジスティック回帰 : 2 本が接近しているので、データを増やしても伸びない。")
    print("                     特徴量を足すか、表現力のあるモデルに替える。")
    print("決定木             : 2 本が開いたままなので過学習。深さを制限し、葉に必要な")
    print("                     最小件数を増やして単純にする。")
    print()

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.0), sharey=True)
    for ax, curve in zip(axes, curves):
        ax.plot(curve["sizes"], curve["train"], marker="o", color="#e45756", label="訓練データ")
        ax.plot(curve["sizes"], curve["valid"], marker="o", color="#4c78a8", label="検証データ")
        ax.set_title(curve["label"])
        ax.set_xlabel("学習に使った件数")
        ax.set_ylim(0.55, 1.03)
        ax.legend(loc="center right")
    axes[0].set_ylabel("ROC AUC（5 分割の平均）")
    fig.suptitle("学習曲線の読み分け（接近＝データ不足ではない / 開いたまま＝過学習）")
    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / "s15_q4_learning_curve.png", dpi=100)
    plt.close(fig)
    print("図を保存しました: outputs/s15_q4_learning_curve.png")


if __name__ == "__main__":
    main()
