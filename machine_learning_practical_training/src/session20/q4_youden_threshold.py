"""問題4 の解答：Youden 指標（TPR - FPR）が最大になる閾値を探し、0.5 との違いを数える。

使い方:
    docker compose exec lab python src/session20/q4_youden_threshold.py
"""

from __future__ import annotations

from common import (
    DEFAULT_THRESHOLD,
    confusion_parts,
    fit_high_rating,
    load_review_table,
    predict_at,
    print_confusion,
    youden_point,
)


def compare(y_true, proba) -> dict[str, object]:
    """Youden の閾値と既定の 0.5 を、混同行列の 4 象限で比べる。"""
    best = youden_point(y_true, proba)
    return {
        "youden": best,
        "at_youden": confusion_parts(y_true, predict_at(proba, best["threshold"])),
        "at_default": confusion_parts(y_true, predict_at(proba, DEFAULT_THRESHOLD)),
    }


def main() -> None:
    df = load_review_table()
    y_test, proba = fit_high_rating(df)
    result = compare(y_test, proba)
    best = result["youden"]
    at_youden = result["at_youden"]
    at_default = result["at_default"]

    print("■ Youden 指標が最大になる点")
    print(f"閾値        : {best['threshold']:.4f}")
    print(f"TPR（再現率）: {best['tpr']:.4f}")
    print(f"FPR         : {best['fpr']:.4f}")
    print(f"TPR - FPR   : {best['youden']:.4f}")
    print()

    print("■ その閾値での混同行列")
    print_confusion(at_youden)
    print()

    print("■ 既定の 0.5 との差（件数で見る）")
    print(f"低評価を正しく低評価と言えた件数（TN）: {at_default['tn']:,} → {at_youden['tn']:,}")
    print(f"低評価を高評価と言ってしまった件数（FP）: {at_default['fp']:,} → {at_youden['fp']:,}")
    print(f"高評価を取りこぼした件数（FN）        : {at_default['fn']:,} → {at_youden['fn']:,}")
    print(f"高評価を正しく拾えた件数（TP）        : {at_default['tp']:,} → {at_youden['tp']:,}")
    print()

    print("■ 判定")
    print(f"閾値は 0.5 より上がったか: {best['threshold'] > DEFAULT_THRESHOLD}")
    print(f"低評価を見分ける力（TN）は増えたか: {at_youden['tn'] > at_default['tn']}")
    print(f"高評価の取りこぼし（FN）も増えたか: {at_youden['fn'] > at_default['fn']}")
    print("→ Youden 指標は 2 種類の間違いを同じ重さで扱う。どちらが痛いかは業務が決める（問題5 へ）。")


if __name__ == "__main__":
    main()
