"""課題5 の解答: 層化 5 分割の交差検証で、ホールドアウト 1 回の見積もりを点検する。

実行:
    docker compose exec lab python src/mid02/validate.py
"""

from __future__ import annotations

import numpy as np

from common import (
    N_SPLITS,
    baseline_scores,
    cancel_probabilities,
    cross_validate_folds,
    load_order_table,
    score_summary,
)

STABLE_LIMIT = 0.05  # fold 間のばらつき・ホールドアウトとの差をこの幅で判定する


def cross_check() -> dict[str, object]:
    """交差検証の結果と、ホールドアウト 1 回の結果を突き合わせる。"""
    rows = cross_validate_folds(load_order_table())
    pr_scores = np.array([row["pr_auc"] for row in rows], dtype="float64")
    roc_scores = np.array([row["roc_auc"] for row in rows], dtype="float64")

    y_test, proba = cancel_probabilities("plain")
    holdout = score_summary(y_test, proba)
    base = baseline_scores(y_test)

    return {
        "rows": rows,
        "n_folds": len(rows),
        "pr_mean": float(pr_scores.mean()),
        "pr_std": float(pr_scores.std()),  # ddof=0（5 つの fold そのもののばらつき）
        "roc_mean": float(roc_scores.mean()),
        "holdout_pr_auc": holdout["pr_auc"],
        "holdout_roc_auc": holdout["roc_auc"],
        "positive_rate": base["positive_rate"],
        "all_above_baseline": bool((pr_scores > base["positive_rate"]).all()),
        "stable": bool(float(pr_scores.std()) < STABLE_LIMIT),
        "consistent": bool(abs(float(pr_scores.mean()) - holdout["pr_auc"]) < STABLE_LIMIT),
    }


def main() -> None:
    result = cross_check()
    rows = result["rows"]

    print(f"■ 1. 層化 {N_SPLITS} 分割の交差検証（fold ごとに前処理を fit し直す）")
    print("fold ごとの検証データの正例率: "
          + " ".join(f"{row['positive_rate']:.3f}" for row in rows))
    print("fold ごとの PR-AUC           : "
          + " ".join(f"{row['pr_auc']:.4f}" for row in rows))
    print("fold ごとの ROC AUC          : "
          + " ".join(f"{row['roc_auc']:.4f}" for row in rows))
    print(f"PR-AUC の平均 / 標準偏差     : {result['pr_mean']:.4f} / {result['pr_std']:.4f}")
    print()

    print("■ 2. ホールドアウト 1 回の見積もりと突き合わせる")
    print(f"ホールドアウトの PR-AUC : {result['holdout_pr_auc']:.4f}")
    print(f"ホールドアウトの ROC AUC: {result['holdout_roc_auc']:.4f}")
    print()

    print("■ 3. 判定")
    print(f"どの fold も PR-AUC がベースライン {result['positive_rate']:.4f} を上回ったか : "
          f"{result['all_above_baseline']}")
    print(f"fold 間の PR-AUC の標準偏差が {STABLE_LIMIT} 未満か : {result['stable']}")
    print(f"ホールドアウトの PR-AUC との差が {STABLE_LIMIT} 未満か : {result['consistent']}")
    print()

    print("■ 4. 読み方")
    print("3 つとも True なら、ホールドアウト 1 回の PR-AUC は「たまたま当たった値」ではありません。")
    print("fold ごとの正例率がそろっているのは stratify（層化）の効果です。層化しないと、")
    print("正例が全体の 3.6% しかないため fold ごとの正例率がばらつき、指標が大きく振れます。")


if __name__ == "__main__":
    main()
