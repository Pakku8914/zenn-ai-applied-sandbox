"""問題1 の解答：混同行列を自分で数え、4 象限から指標を計算する。

使い方:
    docker compose exec lab python src/session20/q1_confusion_by_hand.py
"""

from __future__ import annotations

import numpy as np

from common import (
    DEFAULT_THRESHOLD,
    POSITIVE_LABEL,
    average_scores,
    class_metrics,
    confusion_parts,
    fit_high_rating,
    load_review_table,
    predict_at,
    print_confusion,
)


def count_by_hand(y_true, y_pred) -> dict[str, int]:
    """ブール配列の論理積を数えて 4 象限を作る（sklearn を使わない実装）。"""
    truth = np.asarray(y_true) == POSITIVE_LABEL
    guess = np.asarray(y_pred) == POSITIVE_LABEL
    return {
        "tn": int((~truth & ~guess).sum()),
        "fp": int((~truth & guess).sum()),
        "fn": int((truth & ~guess).sum()),
        "tp": int((truth & guess).sum()),
    }


def metrics_from_parts(parts: dict[str, int]) -> dict[str, float]:
    """4 象限の件数だけから、式どおりに 4 つの指標を計算する。"""
    precision = parts["tp"] / (parts["tp"] + parts["fp"])
    recall = parts["tp"] / (parts["tp"] + parts["fn"])
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall),
        "accuracy": (parts["tp"] + parts["tn"]) / sum(parts.values()),
    }


def agrees_with_sklearn(hand: dict[str, float], library: dict[str, float], scores: dict[str, float]) -> bool:
    """手計算と sklearn の 4 指標が（浮動小数点の誤差の範囲で）一致するかを判定する。"""
    same_class = all(abs(hand[key] - library[key]) < 1e-9 for key in ("precision", "recall", "f1"))
    return bool(same_class and abs(hand["accuracy"] - scores["accuracy"]) < 1e-9)


def main() -> None:
    df = load_review_table()
    y_test, proba = fit_high_rating(df)
    y_pred = predict_at(proba, DEFAULT_THRESHOLD)

    mine = count_by_hand(y_test, y_pred)
    sklearn_parts = confusion_parts(y_test, y_pred)
    print("■ 自分で数えた 4 象限")
    print_confusion(mine)
    print(f"sklearn の confusion_matrix と一致するか: {mine == sklearn_parts}")
    print(f"4 象限の合計 = 評価データの件数か: {sum(mine.values()) == len(y_test)}（{sum(mine.values()):,} 件）")
    print()

    hand = metrics_from_parts(mine)
    library = class_metrics(y_test, y_pred, POSITIVE_LABEL)
    scores = average_scores(y_test, y_pred)
    print("■ 式から計算した指標と sklearn の値")
    print(f"適合率   : 手計算 {hand['precision']:.4f} / sklearn {library['precision']:.4f}")
    print(f"再現率   : 手計算 {hand['recall']:.4f} / sklearn {library['recall']:.4f}")
    print(f"F1       : 手計算 {hand['f1']:.4f} / sklearn {library['f1']:.4f}")
    print(f"accuracy : 手計算 {hand['accuracy']:.4f} / sklearn {scores['accuracy']:.4f}")
    print(f"4 つすべてが sklearn と一致するか: {agrees_with_sklearn(hand, library, scores)}")
    print()

    print("■ 分母の違いを言葉で確かめる")
    print(f"適合率の分母 = 高評価と予測した件数 = TP + FP = {mine['tp'] + mine['fp']:,}")
    print(f"再現率の分母 = 実際に高評価だった件数 = TP + FN = {mine['tp'] + mine['fn']:,}")
    print(f"accuracy の分母 = 全件 = {sum(mine.values()):,}")


if __name__ == "__main__":
    main()
