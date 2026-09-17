"""Pipeline がリークを構造的に防ぐことを確かめる（本文 4 節）。

前処理を 2 種類ならべて、同じ「分割前に fit した」間違いがどれだけ評価を歪めるかを測ります。
① スケーラを全データで fit した場合  → 差はほとんど出ない
② ノイズ 500 列から 10 列を選んだ場合 → 当て推量が「当たって見える」ところまで歪む
そして Pipeline に載せると、どちらも自動的に正しい手順になります。

実行:
    docker compose exec lab python src/session25/leak_by_design.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from common import (
    CATEGORICAL_S17,
    MAX_ITER,
    NUMERIC,
    RANDOM_STATE,
    auc_of,
    build_preprocess,
    cv_auc,
    features_target,
    fmt_scores,
    holdout_auc,
    load_review_table,
    named_frame,
    save_figure,
    split,
    summarize,
)

N_NOISE = 500        # 乱数だけで作る列の数（セッション22 と同じ条件）
K_SELECT = 10        # そのうち「効きそうな」何列を残すか
CHANCE_AUC = 0.5     # 当て推量（無情報）の ROC AUC
CV_TOLERANCE = 0.03  # 交差検証の平均が「当て推量とほぼ同じ」と言える幅
FIGURE_NAME = "s25_leak_by_design.png"


def make_noise(n_rows: int) -> pd.DataFrame:
    """目的変数とまったく関係のない正規乱数の列を 500 本作る（セッション22 と同じ）。"""
    rng = np.random.default_rng(RANDOM_STATE)
    values = rng.normal(size=(n_rows, N_NOISE))
    return pd.DataFrame(values, columns=[f"noise{i:03d}" for i in range(N_NOISE)])


def selection_pipeline() -> Pipeline:
    """特徴量選択をモデルと同じ Pipeline に入れる。fit が訓練データに閉じ込められる。"""
    return Pipeline(
        [
            ("select", SelectKBest(f_classif, k=K_SELECT)),
            ("model", LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        ]
    )


def scaler_leak(df) -> dict[str, float]:
    """① スケーラを分割前に全データで fit した場合（セッション22 で測った実験）。"""
    correct = holdout_auc(df, NUMERIC, CATEGORICAL_S17)  # Pipeline に載せた正しい手順

    X, y = features_target(df, NUMERIC, CATEGORICAL_S17)
    pre = build_preprocess(NUMERIC, CATEGORICAL_S17).fit(X)  # 評価データまで見て fit している
    X_all = named_frame(pre.transform(X), pre.get_feature_names_out(), index=X.index)
    X_train, X_test, y_train, y_test = split(X_all, y)
    model = LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE).fit(X_train, y_train)
    leaked = auc_of(model, X_test, y_test)

    return {"n_columns": int(X_all.shape[1]), "correct": correct, "leaked": leaked, "gap": leaked - correct}


def selection_leak(df) -> dict[str, object]:
    """② ノイズ 500 列から 10 列を選ぶ場合（セッション22 と同じ条件）。"""
    y = df["is_high"]
    X_noise = make_noise(len(df))

    # 手続き的に書くと、選ぶ工程が分割の前に来てしまいやすい
    selector = SelectKBest(f_classif, k=K_SELECT).fit(X_noise, y)
    X_train, X_test, y_train, y_test = split(X_noise.loc[:, selector.get_support()], y)
    leaked_model = LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE).fit(X_train, y_train)
    leaked = auc_of(leaked_model, X_test, y_test)

    # Pipeline に入れると、選ぶ工程も fit の内側に入る
    X_train, X_test, y_train, y_test = split(X_noise, y)
    pipeline = selection_pipeline().fit(X_train, y_train)
    correct = auc_of(pipeline, X_test, y_test)

    # そのまま交差検証にも渡せる（fold ごとに選び直される）
    scores = cv_auc(selection_pipeline(), X_noise, y)
    cv_mean, cv_std = summarize(scores)

    return {
        "shape": X_noise.shape,
        "correct": correct,
        "leaked": leaked,
        "gap": leaked - correct,
        "scores": [float(s) for s in scores],
        "cv_mean": cv_mean,
        "cv_std": cv_std,
        "cv_is_chance": bool(abs(cv_mean - CHANCE_AUC) < CV_TOLERANCE),
    }


def make_figure(scaler: dict, selection: dict) -> str:
    """2 種類の前処理について、正しい手順と分割前に fit した手順を並べる。"""
    import matplotlib.pyplot as plt

    labels = ["Pipeline に載せる\n（正しい手順）", "分割前に fit する\n（リーク）"]
    panels = [
        ("スケーラを全データで fit", [scaler["correct"], scaler["leaked"]], (0.80, 0.84), False),
        ("ノイズ 500 列から 10 列を選ぶ", [selection["correct"], selection["leaked"]], (0.48, 0.58), True),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(9.0, 4.2))
    for ax, (title, values, limits, draw_chance) in zip(axes, panels):
        bars = ax.bar(labels, values, color=["#2980b9", "#c0392b"])
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + (limits[1] - limits[0]) * 0.02,
                f"{value:.4f}",
                ha="center",
                fontsize=10,
            )
        if draw_chance:
            ax.axhline(CHANCE_AUC, color="#7f8c8d", linestyle="--", linewidth=1)
            ax.set_xlabel("破線は当て推量 0.5")
        ax.set_ylim(*limits)
        ax.set_ylabel("ROC AUC")
        ax.set_title(title)
    fig.suptitle("同じ「分割前に fit」でも、歪みの大きさは前処理の種類で違う")
    # 縦軸は左右で違う範囲を拡大している。拡大したことは図の中に書く（セッション8）
    return save_figure(fig, FIGURE_NAME)


def main() -> None:
    df = load_review_table()
    scaler = scaler_leak(df)
    selection = selection_leak(df)

    print("■ 1. スケーラを分割前に全データで fit した場合")
    print(f"変換後の列数                 : {scaler['n_columns']} 列")
    print(f"Pipeline に載せる（正しい）  : {scaler['correct']:.4f}")
    print(f"分割前に fit する（リーク）  : {scaler['leaked']:.4f}")
    print(f"差                           : {scaler['gap']:+.4f}")
    print()

    print("■ 2. ノイズ 500 列から 10 列を選んだ場合")
    print(f"ノイズ列の形                 : {selection['shape']}")
    print(f"Pipeline に載せる（正しい）  : {selection['correct']:.4f}")
    print(f"分割前に選ぶ（リーク）       : {selection['leaked']:.4f}")
    print(f"差                           : {selection['gap']:+.4f}")
    print()

    print("■ 3. Pipeline のまま交差検証に渡す（fold ごとに選び直される）")
    print(f"fold ごとの ROC AUC          : {fmt_scores(selection['scores'])}")
    print(f"平均が当て推量から {CV_TOLERANCE} 以内 : {selection['cv_is_chance']}")
    print()

    print(f"図を保存しました: {make_figure(scaler, selection)}")


if __name__ == "__main__":
    main()
