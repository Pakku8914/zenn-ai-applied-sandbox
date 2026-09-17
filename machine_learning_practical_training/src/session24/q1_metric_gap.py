"""問題1 の解答: 3 つの指標をベースラインと並べ、どれが役に立つかを判断する。

実行:
    docker compose exec lab python src/session24/q1_metric_gap.py
"""

from __future__ import annotations

from common import baseline_scores, cancel_probabilities, score_summary


def summary(y_true, proba) -> dict[str, float]:
    """モデルとベースラインの指標、そしてその差をまとめる。"""
    scores = score_summary(y_true, proba)
    base = baseline_scores(y_true)
    return {
        "roc_auc": scores["roc_auc"],
        "pr_auc": scores["pr_auc"],
        "accuracy": scores["accuracy"],
        "baseline_accuracy": base["accuracy"],
        "baseline_roc_auc": base["roc_auc"],
        "baseline_pr_auc": base["pr_auc"],
        "positive_rate": base["positive_rate"],
        "accuracy_gap": scores["accuracy"] - base["accuracy"],
        "roc_gap": scores["roc_auc"] - base["roc_auc"],
        "pr_gap": scores["pr_auc"] - base["pr_auc"],
    }


def main() -> None:
    y_test, proba = cancel_probabilities("plain")
    result = summary(y_test, proba)

    print("■ 1. モデルの指標（LightGBM・閾値 0.5）")
    print(f"ROC AUC  : {result['roc_auc']:.4f}")
    print(f"PR-AUC   : {result['pr_auc']:.4f}")
    print(f"accuracy : {result['accuracy']:.4f}")
    print()

    print("■ 2. 「全部キャンセルされない」ベースライン")
    print(f"accuracy          : {result['baseline_accuracy']:.4f}")
    print(f"ROC AUC           : {result['baseline_roc_auc']:.4f}")
    print(f"PR-AUC（= 正例率）: {result['baseline_pr_auc']:.4f}")
    print()

    print("■ 3. 差（ROC と PR は小数第 3 位まで）")
    print(f"accuracy : {result['accuracy_gap']:+.4f}")
    print(f"ROC AUC  : {result['roc_gap']:+.3f}")
    print(f"PR-AUC   : {result['pr_gap']:+.3f}")
    print()

    print("■ 4. 言葉にする")
    print("ROC AUC はキャンセルされる注文を上に並べる力を示していて、でたらめより大きく上です。")
    print("PR-AUC は上から順に警告を出したときの当たり具合で、2 割に届きません。")
    print("accuracy はベースラインと同じ値なので、報告に載せる意味がありません。")


if __name__ == "__main__":
    main()
