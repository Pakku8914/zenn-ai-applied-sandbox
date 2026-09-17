"""生スケールの係数と標準化後の係数を並べ、「大きい係数＝重要」が誤りであることを確かめる。

使い方:
    docker compose exec lab python src/session16/coef_scale.py
"""

from __future__ import annotations

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (
    LABEL_JA,
    OUT_DIR,
    coef_series,
    fit_linear,
    load_rated_reviews,
    regression_scores,
    split_xy,
    standardize,
)


def main() -> None:
    df = load_rated_reviews()
    X_train, X_test, y_train, y_test = split_xy(df)

    raw_model = fit_linear(X_train, y_train)
    raw_coefs = coef_series(raw_model, X_train.columns)
    raw_scores = regression_scores(raw_model, X_test, y_test)

    # 標準化は訓練データだけで平均と標準偏差を決める（セッション12の規約）
    X_train_s, X_test_s, _ = standardize(X_train, X_test)
    std_model = fit_linear(X_train_s, y_train)
    std_coefs = coef_series(std_model, X_train_s.columns)
    std_scores = regression_scores(std_model, X_test_s, y_test)

    print("■ 生スケールの係数を絶対値の大きい順に並べる（← してはいけない読み方）")
    for name, value in raw_coefs.abs().sort_values(ascending=False).items():
        print(f"{name:<15}: {raw_coefs[name]:+.6f}（絶対値 {value:.6f}）")

    print("\n■ 標準化後の係数（1 標準偏差ぶん動いたときに星がいくつ動くか）")
    for name, value in std_coefs.items():
        print(f"{name:<15}: {value:+.4f}")

    print("\n■ 大きさの順位（標準化後）")
    ranked = std_coefs.abs().sort_values(ascending=False)
    print(" / ".join(f"{i} 位 {name} {value:.4f}" for i, (name, value) in enumerate(ranked.items(), start=1)))
    print(f"price は body_length の約 {abs(std_coefs['price']) / abs(std_coefs['body_length']):.1f} 倍")

    print("\n■ 尺度を変えても当てはまりは 1 ミリも変わらない")
    print(f"生スケールの R2 {raw_scores['r2']:.4f} / 標準化後の R2 {std_scores['r2']:.4f}")
    # 標準化すると特徴量の平均が 0 になるので、切片は「訓練データの星の平均」そのものになる
    same = bool(np.isclose(std_model.intercept_, y_train.mean()))
    print(f"標準化後の切片が訓練データの星の平均と一致するか : {same}")

    # 図：同じモデルなのに、並べる尺度を変えると順位が入れ替わることを見せる
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    for ax, coefs, title in [
        (axes[0], raw_coefs, "生スケールの係数（比べられない）"),
        (axes[1], std_coefs, "標準化後の係数（比べられる）"),
    ]:
        labels = [LABEL_JA[name] for name in coefs.index]
        colors = ["#4c78a8" if value > 0 else "#d62728" for value in coefs]
        ax.barh(labels, coefs.to_numpy(), color=colors)
        ax.axvline(0, color="#333333", linewidth=0.8)
        ax.set_title(title)
        ax.set_xlabel("星の変化")
        ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s16_coef_scale.png", dpi=110)
    plt.close(fig)
    print("\n図を保存しました: outputs/s16_coef_scale.png")


if __name__ == "__main__":
    main()
