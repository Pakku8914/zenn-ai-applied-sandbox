"""閾値 0.5 の混同行列を数え、AUC 0.7911 の中身を件数で確かめる。

使い方:
    docker compose exec lab python src/session24/confusion_at_default.py
"""

from __future__ import annotations

from common import (
    DEFAULT_THRESHOLD,
    cancel_probabilities,
    confusion_parts,
    predict_at,
    print_confusion,
    score_summary,
)


def main() -> None:
    y_test, proba = cancel_probabilities("plain")
    y_pred = predict_at(proba, DEFAULT_THRESHOLD)
    parts = confusion_parts(y_test, y_pred)
    scores = score_summary(y_test, proba)
    n_rows = sum(parts.values())
    n_positive_pred = parts["fp"] + parts["tp"]

    print(f"■ 閾値 {DEFAULT_THRESHOLD} の混同行列（評価データ {n_rows:,} 件）")
    print_confusion(parts)
    print()

    print("■ この 4 つの数字から分かること")
    print(f"陽性と予測した件数: {n_positive_pred:,} 件（評価データの {n_positive_pred / n_rows:.2%}）")
    print(f"実際のキャンセル  : {parts['fn'] + parts['tp']:,} 件")
    print(f"捕まえられた件数  : {parts['tp']:,} 件")
    print(f"見逃した件数      : {parts['fn']:,} 件")
    print(f"適合率            : {scores['precision']:.4f}")
    print(f"再現率            : {scores['recall']:.4f}")
    print(f"F1                : {scores['f1']:.4f}")
    print(f"accuracy          : {scores['accuracy']:.4f}")


if __name__ == "__main__":
    main()
