"""本文 7 節（Good の書き方）: 4 指標とベースラインをいつもまとめて出すレポート。

指標を 1 つだけ返す関数を書くと、次に別の指標が必要になったときに
呼び出し側をすべて書き換えることになります。最初から一式で返します。
"""

from __future__ import annotations

from common import LGBM, LINEAR, MEAN, METRIC_KEYS, fit_predict_all, print_scores, score_all

REPORT_ORDER = [MEAN, LINEAR, LGBM]  # ベースラインを先頭に置く（比較の基準だから）


def beats(challenger: dict[str, float], baseline: dict[str, float], metric: str) -> bool:
    """指標ごとの「勝ち負け」。R2 だけは大きいほうが良い。"""
    if metric == "r2":
        return challenger[metric] > baseline[metric]
    return challenger[metric] < baseline[metric]


def compare_with_baseline(scores: dict[str, dict[str, float]], baseline_name: str = MEAN):
    """モデルごとに「ベースラインに勝った指標 / 負けた指標」を返す。"""
    baseline = scores[baseline_name]
    result = {}
    for name, values in scores.items():
        if name == baseline_name:
            continue
        won = [key.upper() for key in METRIC_KEYS if beats(values, baseline, key)]
        lost = [key.upper() for key in METRIC_KEYS if not beats(values, baseline, key)]
        result[name] = (won, lost)
    return result


def main() -> None:
    y_test, preds = fit_predict_all()
    scores = score_all(y_test, preds)

    print(f"■ 回帰の評価レポート（評価データ {len(y_test):,} 件）")
    for name in REPORT_ORDER:
        print_scores(name, scores[name])
    print()

    comparison = compare_with_baseline(scores)
    print(f"■ ベースライン（{MEAN}）に勝っている指標")
    for name in [LINEAR, LGBM]:
        print(f"{name}: {', '.join(comparison[name][0])}")
    print()

    print("■ ベースラインに負けている指標")
    for name in [LINEAR, LGBM]:
        print(f"{name}: {', '.join(comparison[name][1])}")
    print()

    perfect = [name for name, (won, lost) in comparison.items() if not lost]
    print(f"■ 4 つの指標すべてでベースラインに勝ったモデルはあるか: {bool(perfect)}")


if __name__ == "__main__":
    main()
