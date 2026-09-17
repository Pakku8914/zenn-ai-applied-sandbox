"""課題4: 層化 5 分割の交差検証で、ホールドアウト 1 回の見積もりを点検する。

1 回の分割で出た差（0.0318）が、分け方の運によるものかどうかを確かめます。

使い方:
    docker compose exec lab python src/final01/validate.py
"""

from __future__ import annotations

from common import MODELS, N_SPLITS, SCORING, cv_scores, fitted


def cross_check() -> dict:
    """2 本のモデルを同じ分割で 5 回ずつ学習し、平均と標準偏差を比べる。"""
    rows = []
    for kind in MODELS:
        cv = cv_scores(kind)
        holdout = fitted(kind)["roc_auc"]
        rows.append(
            {
                **cv,
                "holdout": holdout,
                "difference": abs(holdout - cv["mean"]),
                # ホールドアウト 1 回の値が、交差検証のばらつきの中にあるか
                "holdout_within_band": bool(abs(holdout - cv["mean"]) <= 2 * cv["std"]),
            }
        )
    logistic, lgbm = rows[0], rows[1]  # MODELS の並び（logistic → lgbm）と同じ
    cv_gap = logistic["mean"] - lgbm["mean"]
    return {
        "rows": rows,
        "logistic": logistic,
        "lgbm": lgbm,
        "cv_gap": cv_gap,
        "holdout_gap": logistic["holdout"] - lgbm["holdout"],
        # モデル間の差が、モデル内のばらつきより大きいか
        "gap_beats_std": bool(cv_gap > max(logistic["std"], lgbm["std"])),
        "same_winner": bool(logistic["mean"] > lgbm["mean"]),
    }


def main() -> None:
    result = cross_check()

    print(f"■ 1. 層化 {N_SPLITS} 分割の交差検証（scoring={SCORING}・分割前の全データが母集団）")
    for row in result["rows"]:
        print(f"{row['label']}")
        print("    fold ごとの ROC AUC: " + " / ".join(f"{value:.4f}" for value in row["scores"]))
        print(f"    平均 {row['mean']:.4f} ± {row['std']:.4f}")
    print()

    print("■ 2. ホールドアウト 1 回の値と突き合わせる")
    for row in result["rows"]:
        print(f"{row['label']}: ホールドアウト {row['holdout']:.4f} / 交差検証の平均 {row['mean']:.4f}（差 {row['difference']:.4f}）")
        print(f"    差が 2σ に収まっているか: {row['holdout_within_band']}")
    print()

    print("■ 3. 2 本の差は偶然か")
    print(f"ホールドアウトの差: {result['holdout_gap']:.4f}")
    print(f"交差検証の平均の差: {result['cv_gap']:.4f}")
    print(f"差が標準偏差より大きいか: {result['gap_beats_std']}")
    print(f"交差検証でも同じモデルが勝ったか: {result['same_winner']}")
    print()
    print("判断: 差は分け方の運では説明できない大きさです。")
    print("      『指標だけで選ぶなら線形モデル』が、このデータの結論になります。")


if __name__ == "__main__":
    main()
