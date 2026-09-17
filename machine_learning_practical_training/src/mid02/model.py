"""課題2 の解答: 基準モデルを学習し、報告してよい指標だけを並べる。

実行:
    docker compose exec lab python src/mid02/model.py
"""

from __future__ import annotations

from common import (
    DEFAULT_THRESHOLD,
    baseline_scores,
    cancel_probabilities,
    confusion_parts,
    predict_at,
    print_confusion,
    score_summary,
)


def scores() -> dict[str, object]:
    """基準モデルの指標と、ベースラインからの伸びをまとめて返す。"""
    y_test, proba = cancel_probabilities("plain")
    model = score_summary(y_test, proba)
    base = baseline_scores(y_test)
    parts = confusion_parts(y_test, predict_at(proba, DEFAULT_THRESHOLD))
    return {
        **model,
        "base_accuracy": base["accuracy"],
        "base_roc_auc": base["roc_auc"],
        "base_pr_auc": base["pr_auc"],
        "positive_rate": base["positive_rate"],
        "n_positive": base["n_positive"],
        "roc_gain": model["roc_auc"] - base["roc_auc"],
        "pr_lift": model["pr_auc"] / base["pr_auc"],
        "accuracy_gap": model["accuracy"] - base["accuracy"],
        "parts": parts,
    }


def main() -> None:
    result = scores()
    parts = result["parts"]

    print("■ 1. 基準モデル（特徴量 5 列・LightGBM n_estimators=200）")
    print(f"ROC AUC        : {result['roc_auc']:.4f}"
          f"（ベースライン {result['base_roc_auc']:.4f} から +{result['roc_gain']:.4f}）")
    print(f"PR-AUC         : {result['pr_auc']:.4f}"
          f"（ベースライン {result['base_pr_auc']:.4f} の {result['pr_lift']:.1f} 倍）")
    print(f"accuracy       : {result['accuracy']:.4f}"
          f"（ベースラインとの差 {result['accuracy_gap']:+.4f}。報告には使わない）")
    print(f"Brier スコア   : {result['brier']:.5f}")
    print(f"予測確率の平均 : {result['mean_proba']:.4f}（実際の正例率 {result['positive_rate']:.4f}）")
    print()

    print("■ 2. 閾値 0.5 の混同行列")
    print_confusion(parts)
    print()

    print(f"実際にキャンセルされた {result['n_positive']:,} 件のうち、捕まえたのは"
          f" {parts['tp']:,} 件（再現率 {result['recall']:.4f}）")
    print(f"陽性と予測したのは {parts['fp'] + parts['tp']:,} 件で、当たりは"
          f" {parts['tp']:,} 件（適合率 {result['precision']:.4f}）")
    print(f"正解した件数 {parts['tn'] + parts['tp']:,} 件は、ベースラインの正解件数と同じです")


if __name__ == "__main__":
    main()
