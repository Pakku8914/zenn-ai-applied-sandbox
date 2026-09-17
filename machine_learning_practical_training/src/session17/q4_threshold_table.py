"""問題4 の解答: 閾値を 5 段階に動かして指標の変化を表にし、目的から閾値を選ぶ。

使い方:
    docker compose exec lab python src/session17/q4_threshold_table.py
"""

from __future__ import annotations

import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

from common import THRESHOLDS, fit_model, load_review_table, prepare, split_xy

PRECISION_TARGET = 0.95  # 「陽性と言ったら外したくない」場合の目標
RECALL_TARGET = 0.99  # 「見落としたくない」場合の目標


def metrics_at(y_true, proba, threshold: float) -> dict[str, float]:
    """閾値を 1 つ決めたときの 5 つの数値をまとめる。指標は自分で計算する。"""
    y_pred = (proba >= threshold).astype("int64")
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "n_positive": int(y_pred.sum()),
        "accuracy": float(accuracy_score(y_true, y_pred)),
    }


def build_table(y_true, proba, thresholds=None) -> pd.DataFrame:
    """閾値ごとの指標を縦に並べた表を作る。"""
    targets = THRESHOLDS if thresholds is None else thresholds
    return pd.DataFrame([metrics_at(y_true, proba, t) for t in targets])


def lowest_threshold_for(table: pd.DataFrame, column: str, target: float) -> float | None:
    """指定した指標が target 以上になる閾値のうち、いちばん低いものを返す。"""
    hit = table.loc[table[column] >= target].sort_values("threshold")
    return None if hit.empty else float(hit.iloc[0]["threshold"])


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    model = fit_model(train, y_train)
    proba = model.predict_proba(test)[:, 1]

    table = build_table(y_test, proba)
    print("■ 閾値を動かしたときの指標（陽性 = 高評価）")
    print("閾値 | 適合率 | 再現率 |   F1   | 陽性と予測 | accuracy")
    for row in table.itertuples(index=False):
        print(
            f"{row.threshold:.1f}  | {row.precision:.4f} | {row.recall:.4f} | {row.f1:.4f} |"
            f" {row.n_positive:>6,} 件 | {row.accuracy:.4f}"
        )
    print()

    print("■ 目的から閾値を選ぶ")
    strict = lowest_threshold_for(table, "precision", PRECISION_TARGET)
    wide = lowest_threshold_for(table, "recall", RECALL_TARGET)
    strict_row = table.loc[table["threshold"] == strict].iloc[0]
    wide_row = table.loc[table["threshold"] == wide].iloc[0]
    print(f"① 適合率 {PRECISION_TARGET:.2f} 以上にしたい → 閾値 {strict:.1f}"
          f"（適合率 {strict_row['precision']:.4f} / 再現率 {strict_row['recall']:.4f}）")
    print(f"② 再現率 {RECALL_TARGET:.2f} 以上にしたい → 閾値 {wide:.1f}"
          f"（適合率 {wide_row['precision']:.4f} / 再現率 {wide_row['recall']:.4f}）")
    best = table.loc[table["accuracy"].idxmax()]
    print(f"③ accuracy が最大 → 閾値 {best['threshold']:.1f}（accuracy {best['accuracy']:.4f}）")
    print()
    print("判断: ①は「推薦した本が外れていると信用を失う」場面向けです。ただし再現率が半分近くまで落ちるため、")
    print("      紹介できる本の数は大きく減ります。②は「候補をできるだけ拾う」場面向けで、適合率は下がります。")
    print("      ③の accuracy 最大は「多数派に合わせただけ」になりやすく、業務上の目的とは無関係です。")


if __name__ == "__main__":
    main()
