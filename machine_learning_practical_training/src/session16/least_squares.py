"""最小二乗法が何を最小にしているのかを、5 点だけの練習データで確かめる。

使い方:
    docker compose exec lab python src/session16/least_squares.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 画面を持たない環境なので画像ファイルに保存する
import matplotlib.pyplot as plt

from common import OUT_DIR, fit_linear, line_pred, make_toy_line, sse

# 「どれがいちばんマシか」を比べる 3 本の候補線（傾き, 切片, 図に出す色）
CANDIDATES = [(2.0, 0.0, "#d62728"), (1.5, 1.5, "#ff7f0e"), (1.7, 0.9, "#4c78a8")]


def main() -> None:
    toy = make_toy_line()
    x, y = toy["x"], toy["y"]

    print("■ 5 点の練習データ")
    print(f"x : {list(x)}")
    print(f"y : {list(y)}")

    print("\n■ 3 本の候補線の残差二乗和（SSE）")
    for slope, intercept, _ in CANDIDATES:
        print(f"傾き {slope:.1f} / 切片 {intercept:.1f} : SSE {sse(y, line_pred(x, slope, intercept)):.3f}")
    mean_sse = sse(y, line_pred(x, 0.0, float(y.mean())))
    print(f"平均だけを返す線（傾き 0.0 / 切片 {y.mean():.1f}）: SSE {mean_sse:.3f}")

    print("\n■ LinearRegression が選んだ線")
    model = fit_linear(toy[["x"]], y)
    slope = float(model.coef_[0])
    intercept = float(model.intercept_)
    best_sse = sse(y, model.predict(toy[["x"]]))
    print(f"傾き {slope:.4f} / 切片 {intercept:.4f} / SSE {best_sse:.3f}")
    print(f"決定係数 R2            : {model.score(toy[['x']], y):.4f}")
    print(f"1 - SSE / 平均線の SSE : {1 - best_sse / mean_sse:.4f}")
    print(f"残差の合計が 0 か      : {abs(float((y - model.predict(toy[['x']])).sum())) < 1e-9}")

    # 図：同じ 5 点に 3 本の線を重ね、どれだけ外しているかを縦線で描く
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.4), sharey=True)
    for ax, (cand_slope, cand_intercept, color) in zip(axes, CANDIDATES):
        pred = line_pred(x, cand_slope, cand_intercept)
        ax.scatter(x, y, color="#333333", zorder=3, label="実際の値")
        ax.plot(x, pred, color=color, label="候補の直線")
        ax.vlines(x, pred, y, color=color, linestyle=":", linewidth=1.2)
        ax.set_title(f"傾き {cand_slope:.1f} / 切片 {cand_intercept:.1f}\nSSE {sse(y, pred):.2f}")
        ax.set_xlabel("x")
    axes[0].set_ylabel("y")
    axes[0].legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s16_least_squares.png", dpi=110)
    plt.close(fig)
    print("\n図を保存しました: outputs/s16_least_squares.png")


if __name__ == "__main__":
    main()
