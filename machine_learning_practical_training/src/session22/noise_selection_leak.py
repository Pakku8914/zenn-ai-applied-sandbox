"""中身が完全な雑音の 500 列から「効く 10 列」を選ぶと何が起きるか（本文 5 節）。

実行:
    docker compose exec lab python src/session22/noise_selection_leak.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from common import MAX_ITER, OUT_DIR, RANDOM_STATE, TEST_SIZE, load_review_table, save_figure

N_NOISE = 500       # 乱数だけで作る列の数
K_SELECT = 10       # そのうち「効きそうな」何列を残すか
CHANCE_AUC = 0.5    # 当て推量（無情報）の ROC AUC
FIGURE_NAME = "s22_leak_gap.png"


def make_noise(n_rows: int) -> pd.DataFrame:
    """目的変数とまったく関係のない正規乱数の列を 500 本作る。"""
    rng = np.random.default_rng(RANDOM_STATE)
    values = rng.normal(size=(n_rows, N_NOISE))
    return pd.DataFrame(values, columns=[f"noise{i:03d}" for i in range(N_NOISE)])


def split(X, y):
    """分割の条件は全章で共通。X の中身が何であっても同じ行が評価データになる。"""
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def leaked(X_noise: pd.DataFrame, y: pd.Series) -> tuple[float, list[str]]:
    """リークする手順: 分割の前に、全データを見て 10 列を選ぶ。"""
    selector = SelectKBest(f_classif, k=K_SELECT).fit(X_noise, y)
    X_selected = X_noise.loc[:, selector.get_support()]  # 選ばれた 10 列だけを残す
    X_train, X_test, y_train, y_test = split(X_selected, y)
    model = LogisticRegression(max_iter=MAX_ITER).fit(X_train, y_train)
    auc = float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))
    return auc, list(X_selected.columns)


def honest(X_noise: pd.DataFrame, y: pd.Series) -> tuple[float, list[str]]:
    """正しい手順: 分割してから、訓練データだけを見て 10 列を選ぶ。"""
    X_train, X_test, y_train, y_test = split(X_noise, y)
    model = Pipeline(
        [
            # 特徴量選択も「学習」なので、Pipeline に入れて fit を訓練データに閉じ込める
            ("select", SelectKBest(f_classif, k=K_SELECT)),
            ("model", LogisticRegression(max_iter=MAX_ITER)),
        ]
    ).fit(X_train, y_train)
    auc = float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))
    chosen = list(X_train.columns[model.named_steps["select"].get_support()])
    return auc, chosen


def experiment(df) -> dict[str, object]:
    """リークあり・なしの 2 通りを同じノイズ・同じ分割で比べる。"""
    y = df["is_high"]
    X_noise = make_noise(len(df))
    leaked_auc, leaked_columns = leaked(X_noise, y)
    honest_auc, honest_columns = honest(X_noise, y)
    return {
        "shape": X_noise.shape,
        "leaked_auc": leaked_auc,
        "honest_auc": honest_auc,
        "gap": leaked_auc - honest_auc,
        "leaked_columns": leaked_columns,
        "honest_columns": honest_columns,
        "overlap": len(set(leaked_columns) & set(honest_columns)),
    }


def make_figure(result: dict) -> str:
    """リークあり・なし・当て推量の 3 本を棒グラフで並べる。"""
    import matplotlib.pyplot as plt

    labels = ["分割前に選ぶ\n（リーク）", "訓練データだけで選ぶ\n（正しい手順）", "当て推量"]
    values = [result["leaked_auc"], result["honest_auc"], CHANCE_AUC]
    fig, ax = plt.subplots(figsize=(6.5, 4.0))
    bars = ax.bar(labels, values, color=["#c0392b", "#2980b9", "#7f8c8d"])
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.002, f"{value:.4f}", ha="center", fontsize=10)
    ax.axhline(CHANCE_AUC, color="#7f8c8d", linestyle="--", linewidth=1)
    ax.set_ylim(0.45, 0.60)
    ax.set_ylabel("ROC AUC")
    ax.set_title("中身が雑音だけの 500 列でも、選び方を間違えると当たって見える")
    # 縦軸を 0 から描くと差が見えないので拡大している。拡大したことは図の中に書く（セッション8）
    ax.set_xlabel("縦軸は当て推量 0.5 の付近を拡大しています")
    path = save_figure(fig, FIGURE_NAME)
    return str(path.relative_to(OUT_DIR.parent))


def main() -> None:
    df = load_review_table()
    result = experiment(df)

    print(f"ノイズ列の形（行数・列数）                     : {result['shape']}")
    print(f"① 分割前に全データで 10 列を選んだ ROC AUC     : {result['leaked_auc']:.4f}")
    print(f"② 分割後に訓練データだけで選んだ ROC AUC       : {result['honest_auc']:.4f}")
    print(f"③ 当て推量（中身が雑音なら本来こうなる）       : {CHANCE_AUC:.4f}")
    print(f"④ ① − ②（選び方だけで生まれた差）             : {result['gap']:+.4f}")
    print(f"⑤ ① と ② で選ばれた列の重なり                 : {result['overlap']} / {K_SELECT} 列")
    print()
    print(f"図を保存しました: {make_figure(result)}")


if __name__ == "__main__":
    main()
