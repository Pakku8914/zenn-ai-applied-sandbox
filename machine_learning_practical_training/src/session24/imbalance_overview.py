"""不均衡の度合いを確かめ、「全部しない」と答えるベースラインと accuracy を比べる。

使い方:
    docker compose exec lab python src/session24/imbalance_overview.py
"""

from __future__ import annotations

from common import (
    baseline_scores,
    cancel_probabilities,
    confusion_parts,
    describe_split,
    load_cancel_table,
    predict_at,
    score_summary,
)


def main() -> None:
    df = load_cancel_table()
    counts = describe_split(df)

    print("■ 1. キャンセル予測の母集団")
    print(f"行数        : {counts['n_rows']:,}")
    print(f"訓練データ  : {counts['n_train']:,} 件（正例 {counts['n_train_positive']:,} 件 / 正例率 {counts['rate_train']:.4f}）")
    print(f"評価データ  : {counts['n_test']:,} 件（正例 {counts['n_test_positive']:,} 件 / 正例率 {counts['rate_test']:.4f}）")
    print(f"全体の正例率: {counts['rate_all']:.4f}")
    print()

    y_test, proba = cancel_probabilities("plain")
    base = baseline_scores(y_test)
    scores = score_summary(y_test, proba)

    print("■ 2. 「全部キャンセルされない」と答えるだけのベースライン")
    print(f"accuracy          : {base['accuracy']:.4f}")
    print(f"ROC AUC           : {base['roc_auc']:.4f}")
    print(f"PR-AUC（= 正例率）: {base['pr_auc']:.4f}")
    print()

    print("■ 3. LightGBM（n_estimators=200・閾値 0.5）")
    print(f"accuracy          : {scores['accuracy']:.4f}")
    print(f"ベースラインとの差: {scores['accuracy'] - base['accuracy']:+.4f}")
    print()

    parts = confusion_parts(y_test, predict_at(proba))
    print("■ 4. 正解した件数を数え直す")
    print(f"ベースライン: {parts['tn'] + parts['fp']:,} 件（TN だけ。TP は 0 件）")
    print(f"LightGBM    : {parts['tn'] + parts['tp']:,} 件（TN {parts['tn']:,} + TP {parts['tp']:,}）")
    print(f"TP で増えた件数 {parts['tp']:,} 件と、FP で失った件数 {parts['fp']:,} 件がつり合っています。")


if __name__ == "__main__":
    main()
