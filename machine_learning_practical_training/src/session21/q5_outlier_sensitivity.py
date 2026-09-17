"""問題5 の解答: 評価データの 1 件を差し替え、MAE と RMSE の頑健さを比べる。"""

from __future__ import annotations

from common import LGBM, fit_predict_all, regression_scores

SWAP_VALUES = [6.0, 10.0, 20.0]  # 星の上限 5 を超える値を 3 段階で入れてみる


def sweep(y_test, pred, values: list[float]):
    """差し替えなしと、各値に差し替えたときの指標を返す。"""
    base = regression_scores(y_test, pred)
    swapped = {}
    for value in values:
        y_swapped = y_test.copy()  # 元の評価データは壊さない
        y_swapped.iloc[0] = value
        swapped[value] = regression_scores(y_swapped, pred)
    return base, swapped


def deltas(base: dict[str, float], swapped: dict[float, dict[str, float]]) -> dict[float, dict[str, float]]:
    """差し替えなしとの差（MAE・RMSE）と、その比を求める。"""
    result = {}
    for value, scores in swapped.items():
        mae_delta = scores["mae"] - base["mae"]
        rmse_delta = scores["rmse"] - base["rmse"]
        result[value] = {"mae": mae_delta, "rmse": rmse_delta, "ratio": rmse_delta / mae_delta}
    return result


def main() -> None:
    y_test, preds = fit_predict_all()
    pred = preds[LGBM]

    print(f"■ 評価データの先頭 1 件だけを差し替える（LightGBM・評価データ {len(y_test):,} 件）")
    print(f"差し替えた行の実測: {y_test.iloc[0]:.1f} / 予測: {pred[0]:.4f}")
    print()

    base, swapped = sweep(y_test, pred, SWAP_VALUES)
    print("■ 指標の値")
    print(f"差し替えなし: MAE {base['mae']:.4f} / RMSE {base['rmse']:.4f}")
    for value in SWAP_VALUES:
        print(f"星 {value:4.1f} : MAE {swapped[value]['mae']:.4f} / RMSE {swapped[value]['rmse']:.4f}")
    print()

    diff = deltas(base, swapped)
    print("■ 差し替えなしとの差")
    for value in SWAP_VALUES:
        row = diff[value]
        print(f"星 {value:4.1f} : MAE {row['mae']:+.4f} / RMSE {row['rmse']:+.4f} / RMSE÷MAE {row['ratio']:.2f}")
    print()

    rmse_always_bigger = all(row["rmse"] > row["mae"] for row in diff.values())
    ratios = [diff[value]["ratio"] for value in SWAP_VALUES]
    ratio_grows = all(left < right for left, right in zip(ratios, ratios[1:]))
    slope = (diff[20.0]["mae"] - diff[6.0]["mae"]) / (20.0 - 6.0)

    print("■ 判定")
    print(f"どの値でも RMSE の増え方が MAE より大きいか: {rmse_always_bigger}")
    print(f"差し替える値を大きくすると RMSE÷MAE も大きくなるか: {ratio_grows}")
    print(f"MAE の 1 単位あたりの増え方が 1/{len(y_test)} と一致するか: {abs(slope - 1 / len(y_test)) < 1e-12}")


if __name__ == "__main__":
    main()
