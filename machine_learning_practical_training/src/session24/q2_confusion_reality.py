"""問題2 の解答: 閾値 0.5 の混同行列を数え、AUC 0.7911 の中身を件数で示す。

実行:
    docker compose exec lab python src/session24/q2_confusion_reality.py
"""

from __future__ import annotations

from common import (
    DEFAULT_THRESHOLD,
    cancel_probabilities,
    confusion_parts,
    predict_at,
    print_confusion,
    threshold_metrics,
)


def report(y_true, proba) -> dict[str, float]:
    """閾値 0.5 の 4 象限と、そこから読み取れる件数・指標をまとめる。"""
    parts = confusion_parts(y_true, predict_at(proba, DEFAULT_THRESHOLD))
    row = threshold_metrics(y_true, proba, DEFAULT_THRESHOLD)
    return {
        **parts,
        "n_rows": sum(parts.values()),
        "n_actual_positive": parts["fn"] + parts["tp"],
        "n_predicted_positive": row["n_positive"],
        "precision": row["precision"],
        "recall": row["recall"],
        "f1": row["f1"],
        "caught_per_100": row["recall"] * 100,
    }


def main() -> None:
    y_test, proba = cancel_probabilities("plain")
    result = report(y_test, proba)

    print(f"■ 1. 閾値 {DEFAULT_THRESHOLD} の混同行列（評価データ {result['n_rows']:,} 件）")
    print_confusion({key: result[key] for key in ("tn", "fp", "fn", "tp")})
    print()

    print("■ 2. 数え直す")
    print(f"実際のキャンセル  : {result['n_actual_positive']:,} 件")
    print(f"陽性と予測した件数: {result['n_predicted_positive']:,} 件")
    print(f"捕まえた（TP）    : {result['tp']:,} 件")
    print(f"見逃した（FN）    : {result['fn']:,} 件")
    print(f"空振り（FP）      : {result['fp']:,} 件")
    print(f"再現率            : {result['recall']:.4f}")
    print(f"適合率            : {result['precision']:.4f}")
    print(f"F1                : {result['f1']:.4f}")
    print()

    print("■ 3. 業務の言葉にする")
    print(f"キャンセル 100 件のうち止められるのは {result['caught_per_100']:.1f} 件です。")
    print(f"見逃しが {result['fn']:,} 件あるので、この閾値のままでは運用の役に立ちません。")
    print("一方で、警告を出した 2 件に 1 件は当たっています（適合率 0.5000）。")
    print("つまりモデルの順位付けは機能していて、切る位置だけが合っていません。")


if __name__ == "__main__":
    main()
