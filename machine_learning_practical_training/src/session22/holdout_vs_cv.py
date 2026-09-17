"""1 回の分割と層化 5 分割交差検証を並べて、見積もりのぶれを測る（本文 1 節）。

実行:
    docker compose exec lab python src/session22/holdout_vs_cv.py
"""

from __future__ import annotations

from common import cv_auc, fmt_scores, holdout_auc, load_review_table, stratified_cv, summarize


def compare(df) -> dict[str, object]:
    """ホールドアウト 1 回と層化 5 分割交差検証の結果をまとめて返す。"""
    holdout = holdout_auc(df)
    scores = cv_auc(df, stratified_cv())
    mean, std = summarize(scores)
    return {
        "holdout": holdout,
        "scores": scores,
        "mean": mean,
        "std": std,
        "gap": holdout - mean,          # 1 回の分割が交差検証の平均より甘かった分
        "inside_range": bool(min(scores) <= holdout <= max(scores)),
    }


def main() -> None:
    df = load_review_table()
    print(f"レビュー件数     : {len(df)} 件")
    print(f"高評価の割合     : {df['is_high'].mean():.4f}")
    print()

    result = compare(df)
    print(f"① ホールドアウト 1 回（test_size=0.25）の ROC AUC : {result['holdout']:.4f}")
    print(f"② 層化 5 分割の fold ごとの ROC AUC               : {fmt_scores(result['scores'])}")
    print(f"   平均                                           : {result['mean']:.4f}")
    print(f"   標準偏差                                       : {result['std']:.4f}")
    print(f"③ ① − ②（1 回の分割がどれだけ甘く出たか）        : {result['gap']:+.4f}")
    print(f"④ ① は fold の最小〜最大の中に入っているか        : {result['inside_range']}")


if __name__ == "__main__":
    main()
