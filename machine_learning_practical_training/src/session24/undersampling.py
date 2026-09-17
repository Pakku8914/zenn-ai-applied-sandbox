"""訓練データの負例を捨てて 1:1 にそろえ、評価データでの指標がどう動くかを測る。

使い方:
    docker compose exec lab python src/session24/undersampling.py
"""

from __future__ import annotations

from common import (
    cancel_probabilities,
    load_cancel_table,
    score_summary,
    split_xy,
    undersample,
)


def resample_counts() -> dict[str, int]:
    """アンダーサンプリングの前後で訓練データの件数がどう変わるかを数える。"""
    X_train, _, y_train, _ = split_xy(load_cancel_table())
    X_res, y_res = undersample(X_train, y_train)
    return {
        "before": len(X_train),
        "before_positive": int(y_train.sum()),
        "before_negative": int(len(y_train) - y_train.sum()),
        "after": len(X_res),
        "after_positive": int(y_res.sum()),
        "after_negative": int(len(y_res) - y_res.sum()),
    }


def main() -> None:
    counts = resample_counts()

    print("■ 1. 訓練データを 1:1 にそろえる")
    print(f"元の訓練データ: {counts['before']:,} 件"
          f"（正例 {counts['before_positive']:,} 件 / 負例 {counts['before_negative']:,} 件）")
    print(f"1:1 にした後  : {counts['after']:,} 件"
          f"（正例 {counts['after_positive']:,} 件 / 負例 {counts['after_negative']:,} 件）")
    print(f"捨てた負例    : {counts['before_negative'] - counts['after_negative']:,} 件")
    print()

    y_test, plain = cancel_probabilities("plain")
    _, under = cancel_probabilities("under")
    plain_scores = score_summary(y_test, plain)
    under_scores = score_summary(y_test, under)

    print("■ 2. 評価データ（15,008 件・手を加えていない）での指標")
    print("指標           | 重みなし | 1:1 アンダー")
    print(f"ROC AUC        |  {plain_scores['roc_auc']:.4f}  |  {under_scores['roc_auc']:.4f}")
    print(f"PR-AUC         |  {plain_scores['pr_auc']:.4f}  |  {under_scores['pr_auc']:.4f}")
    print(f"予測確率の平均 |  {plain_scores['mean_proba']:.4f}  |  {under_scores['mean_proba']:.4f}")
    print(f"Brier スコア   | {plain_scores['brier']:.5f}  | {under_scores['brier']:.5f}")
    print()

    print("■ 3. 判定")
    dropped = counts["before_negative"] - counts["after_negative"]
    print(f"PR-AUC は改善したか: {under_scores['pr_auc'] > plain_scores['pr_auc']}")
    print(f"負例を {dropped:,} 件捨てたぶん、モデルが使える情報も減っています。")


if __name__ == "__main__":
    main()
