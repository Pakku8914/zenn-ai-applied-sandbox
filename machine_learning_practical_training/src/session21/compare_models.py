"""本文 3 節: 星の回帰を 3 つのモデルで解き、4 指標を並べて勝者を見る。

この章の山場です。MAE と MAPE では「平均を返すだけ」のモデルが
線形回帰・LightGBM に勝ちます。指標を 1 つしか見ないと結論が逆になります。
"""

from __future__ import annotations

from common import (
    LGBM,
    LINEAR,
    MEAN,
    MODEL_ORDER,
    TARGET,
    best_model,
    fit_predict_all,
    load_rated_reviews,
    print_best,
    print_scores,
    score_all,
)


def star_distribution(df) -> None:
    """星の分布と代表値を表示する。ここがすべての説明の出発点になる。"""
    counts = df[TARGET].value_counts().sort_index()
    print(f"■ 星の分布（{len(df):,} 件）と代表値")
    for star, count in counts.items():
        print(f"星 {star:.1f}: {count:,} 件")
    print(
        f"平均 {df[TARGET].mean():.4f} / 中央値 {df[TARGET].median():.1f}"
        f" / 標準偏差 {df[TARGET].std(ddof=0):.4f}"
    )


def main() -> None:
    df = load_rated_reviews()
    star_distribution(df)
    print()

    y_test, preds = fit_predict_all(df)
    scores = score_all(y_test, preds)

    print(f"■ 星の回帰（評価データ {len(y_test):,} 件）の指標")
    for name in MODEL_ORDER:
        print_scores(name, scores[name])
    print()

    print("■ 指標ごとにいちばん良いモデル")
    print_best(scores)
    print()

    mae_wins = scores[MEAN]["mae"] < min(scores[LINEAR]["mae"], scores[LGBM]["mae"])
    mape_wins = scores[MEAN]["mape"] < min(scores[LINEAR]["mape"], scores[LGBM]["mape"])
    rmse_last = scores[MEAN]["rmse"] > max(scores[LINEAR]["rmse"], scores[LGBM]["rmse"])
    mismatch = best_model(scores, "mae") != best_model(scores, "rmse")

    print(f"■ 平均予測が返している定数: {preds[MEAN][0]:.2f}")
    print(f"■ MAE では平均予測が 2 つのモデルに勝っているか: {mae_wins}")
    print(f"■ MAPE でも平均予測がいちばん小さいか: {mape_wins}")
    print(f"■ RMSE では平均予測が最下位か: {rmse_last}")
    print(f"■ MAE の 1 位と RMSE の 1 位が違うモデルか: {mismatch}")


if __name__ == "__main__":
    main()
