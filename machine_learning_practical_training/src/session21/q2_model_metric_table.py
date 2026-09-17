"""問題2 の解答: 3 モデル × 4 指標の表を作り、指標ごとの 1 位と最下位を出す。"""

from __future__ import annotations

from common import (
    MEAN,
    METRIC_KEYS,
    MODEL_ORDER,
    fit_predict_all,
    print_scores,
    score_all,
)


def ranking(scores: dict[str, dict[str, float]], metric: str) -> tuple[str, str]:
    """(1 位のモデル名, 最下位のモデル名) を返す。R2 だけは大きいほうが良い。"""
    order = sorted(scores, key=lambda name: scores[name][metric], reverse=(metric == "r2"))
    return order[0], order[-1]


def count_firsts(scores: dict[str, dict[str, float]], name: str) -> int:
    """そのモデルが 1 位になった指標の数。"""
    return sum(1 for metric in METRIC_KEYS if ranking(scores, metric)[0] == name)


def main() -> None:
    y_test, preds = fit_predict_all()
    scores = score_all(y_test, preds)

    print(f"■ 3 モデル × 4 指標（評価データ {len(y_test):,} 件）")
    for name in MODEL_ORDER:
        print_scores(name, scores[name])
    print()

    print("■ 指標ごとの 1 位と最下位")
    for metric in METRIC_KEYS:
        first, last = ranking(scores, metric)
        print(f"{metric.upper():<4}: 1 位 {first} / 最下位 {last}")
    print()

    mae_first = ranking(scores, "mae")[0]
    rmse_first = ranking(scores, "rmse")[0]
    print("■ 判定")
    print(f"MAE の 1 位と RMSE の 1 位は違うモデルか: {mae_first != rmse_first}")
    print(f"MAE だけを見て選ぶと採用するモデル: {mae_first}")
    print(f"RMSE だけを見て選ぶと採用するモデル: {rmse_first}")
    print(f"{MEAN}は 4 指標のうちいくつで 1 位か: {count_firsts(scores, MEAN)}")


if __name__ == "__main__":
    main()
