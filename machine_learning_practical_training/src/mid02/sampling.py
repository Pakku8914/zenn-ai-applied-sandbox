"""課題8 の解答: class_weight とアンダーサンプリングの代償を Brier スコアで測る。

実行:
    docker compose exec lab python src/mid02/sampling.py
"""

from __future__ import annotations

from common import (
    DEFAULT_THRESHOLD,
    KIND_NAMES,
    MODEL_KINDS,
    baseline_scores,
    cancel_probabilities,
    confusion_parts,
    load_order_table,
    predict_at,
    score_summary,
    split_xy,
    undersample,
)

CLOSE_ENOUGH = 0.05  # 予測確率の平均が実際の正例率に「近い」と言える幅


def compare_sampling() -> dict[str, object]:
    """3 つの学習のしかた（重みなし・balanced・1:1）の指標と件数をまとめる。"""
    scores: dict[str, dict[str, float]] = {}
    parts: dict[str, dict[str, int]] = {}
    for kind in MODEL_KINDS:
        y_test, proba = cancel_probabilities(kind)
        scores[kind] = score_summary(y_test, proba)
        parts[kind] = confusion_parts(y_test, predict_at(proba, DEFAULT_THRESHOLD))

    y_test, _ = cancel_probabilities("plain")
    rate = baseline_scores(y_test)["positive_rate"]

    X_train, X_test, y_train, _ = split_xy(load_order_table())
    X_res, y_res = undersample(X_train, y_train)

    plain = scores["plain"]
    return {
        "scores": scores,
        "parts": parts,
        "positive_rate": rate,
        "n_before": len(X_train),
        "n_before_positive": int(y_train.sum()),
        "n_before_negative": int(len(y_train) - y_train.sum()),
        "n_after": len(X_res),
        "n_after_positive": int(y_res.sum()),
        "n_after_negative": int(len(y_res) - y_res.sum()),
        "n_dropped": int(len(y_train) - y_train.sum()) - int(len(y_res) - y_res.sum()),
        "rate_after": float(y_res.mean()),
        "n_test": len(X_test),
        "pr_improved": {
            kind: scores[kind]["pr_auc"] > plain["pr_auc"] for kind in ("balanced", "under")
        },
        "brier_worse": {
            kind: scores[kind]["brier"] > plain["brier"] for kind in ("balanced", "under")
        },
        "mean_close": {
            kind: abs(scores[kind]["mean_proba"] - rate) < CLOSE_ENOUGH
            for kind in ("balanced", "under")
        },
        "mean_ratio": {
            kind: scores[kind]["mean_proba"] / plain["mean_proba"] for kind in ("balanced", "under")
        },
    }


def main() -> None:
    result = compare_sampling()
    scores, parts = result["scores"], result["parts"]

    print("■ 1. 順位の性能（並べ替えの良さ）はほとんど動かない")
    for kind in MODEL_KINDS:
        print(f"{KIND_NAMES[kind]} : ROC AUC {scores[kind]['roc_auc']:.4f}"
              f" / PR-AUC {scores[kind]['pr_auc']:.4f}")
    print()

    print("■ 2. 確率は壊れる")
    for kind in MODEL_KINDS:
        print(f"{KIND_NAMES[kind]} : 予測確率の平均 {scores[kind]['mean_proba']:.4f}"
              f" / Brier スコア {scores[kind]['brier']:.5f}")
    print(f"（実際の正例率は {result['positive_rate']:.4f}）")
    print()

    print("■ 3. 閾値 0.5 の見え方（重みなし → balanced）")
    print(f"適合率       : {scores['plain']['precision']:.4f} → {scores['balanced']['precision']:.4f}")
    print(f"再現率       : {scores['plain']['recall']:.4f} → {scores['balanced']['recall']:.4f}")
    print(f"捕まえた件数 : {parts['plain']['tp']:,} 件 → {parts['balanced']['tp']:,} 件")
    print(f"見逃した件数 : {parts['plain']['fn']:,} 件 → {parts['balanced']['fn']:,} 件")
    print()

    print("■ 4. 1:1 アンダーサンプリングで捨てたデータ")
    print(f"訓練 {result['n_before']:,} 件（正例 {result['n_before_positive']:,}"
          f" / 負例 {result['n_before_negative']:,}）"
          f" → {result['n_after']:,} 件（正例 {result['n_after_positive']:,}"
          f" / 負例 {result['n_after_negative']:,}）")
    print(f"捨てた負例 : {result['n_dropped']:,} 件（そろえた後の正例率 {result['rate_after']:.4f}）")
    print(f"評価データ {result['n_test']:,} 件には手を加えていない")
    print()

    print("■ 5. 判定（balanced / under）")
    print(f"PR-AUC は改善したか : {result['pr_improved']['balanced']}"
          f" / {result['pr_improved']['under']}")
    print(f"Brier スコアは悪化したか : {result['brier_worse']['balanced']}"
          f" / {result['brier_worse']['under']}")
    print(f"確率の平均は実際の正例率に近いか : {result['mean_close']['balanced']}"
          f" / {result['mean_close']['under']}")
    print(f"確率の平均は重みなしの何倍か : {result['mean_ratio']['balanced']:.1f} 倍"
          f" / {result['mean_ratio']['under']:.1f} 倍")
    print()

    print("■ 6. 読み方")
    print("順位（誰が危ないか）はほぼ同じで、確率の水準だけが壊れます。")
    print(f"balanced の確率をそのまま報告すると「キャンセル率"
          f" {scores['balanced']['mean_proba']:.1%}」と書いてしまいます"
          f"（実際は {result['positive_rate']:.2%}）。")
    print("確率を使うなら重みなし、閾値で切った件数だけを使うならどれでも構いません。")


if __name__ == "__main__":
    main()
