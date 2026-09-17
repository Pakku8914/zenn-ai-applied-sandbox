"""問題5 の解答：見逃しと誤検出の重みから、総コストが最小になる閾値を選ぶ。

使い方:
    docker compose exec lab python src/session20/q5_cost_threshold.py
"""

from __future__ import annotations

from common import (
    COST_SETTINGS,
    DEFAULT_THRESHOLD,
    best_cost_threshold,
    cost_row,
    fit_high_rating,
    load_review_table,
)


def decide(y_true, proba) -> list[dict[str, object]]:
    """コストの重みごとに「最小の閾値」と「0.5 のままの総コスト」を並べる。"""
    rows = []
    for miss_cost, alarm_cost in COST_SETTINGS:
        best = best_cost_threshold(y_true, proba, miss_cost, alarm_cost)
        default = cost_row(y_true, proba, DEFAULT_THRESHOLD, miss_cost, alarm_cost)
        rows.append(
            {
                "miss_cost": miss_cost,
                "alarm_cost": alarm_cost,
                "best_threshold": best["threshold"],
                "best_cost": best["total_cost"],
                "default_cost": default["total_cost"],
                "saved": default["total_cost"] - best["total_cost"],
            }
        )
    return rows


def main() -> None:
    df = load_review_table()
    y_test, proba = fit_high_rating(df)

    print("■ 総コストが最小になる閾値（0.05 刻み）")
    for row in decide(y_test, proba):
        print(
            f"見逃し : 誤検出 = {row['miss_cost']} : {row['alarm_cost']} → 閾値 {row['best_threshold']:.2f}"
            f"（総コスト {row['best_cost']:,.0f}）"
        )
    print()

    print("■ 閾値 0.5 のままだと、どれだけ損をするか")
    for row in decide(y_test, proba):
        print(
            f"見逃し : 誤検出 = {row['miss_cost']} : {row['alarm_cost']} →"
            f" 0.5 のとき {row['default_cost']:,.0f} / 最小 {row['best_cost']:,.0f}"
            f"（差 {row['saved']:,.0f}）"
        )
    print()

    print("■ 読み取れること")
    print("見逃しが痛いほど閾値は下がり（拾う数を増やす）、誤検出が痛いほど閾値は上がる（確信がある分だけ拾う）。")
    print("1 : 1 のときだけ閾値 0.50 が最小になる。0.5 は「2 種類の間違いが同じ重さ」という仮定のもとでの答え。")


if __name__ == "__main__":
    main()
